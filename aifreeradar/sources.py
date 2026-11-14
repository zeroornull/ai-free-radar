"""Managed source collection with conditional fetching, versions, and soft rules.

The pipeline never performs HTTP itself: it receives the research transport callback that
owns DNS pinning, robots, pacing, and run budgets. Parsing and rule replay are network-free.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from .config import Settings
from .models import (
    Category,
    RuleMatch,
    SourceDefinition,
    SourceEntry,
    SourceSnapshot,
    SourceState,
    utc_now,
)
from .source_diff import link_changes, text_diff
from .source_parsing import ParsedItem, parse_catalog, parse_feed, parse_web, public_link

if TYPE_CHECKING:
    from .research import FetchedPage
    from .storage import Repository

FetchCallback = Callable[[str, dict[str, str]], Awaitable["FetchedPage"]]

# A server may return a very large rolling feed or catalog. Bound it explicitly.
MAX_ENTRIES_PER_SOURCE = 5000


@dataclass
class SourceScan:
    entries: list[SourceEntry] = field(default_factory=list)
    snapshots: list[SourceSnapshot] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_url(value: str) -> str:
    """Normalize only inert public links; full DNS/redirect safety stays in the transport."""
    normalized = public_link(value, value) or value.strip()
    parsed = urlsplit(normalized)
    if not parsed.hostname:
        return normalized
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            parsed.query,
            "",
        )
    )

def configured_sources(settings: Settings) -> list[SourceDefinition]:
    """Merge explicit managed sources with deterministic definitions from direct_sources.

    A URL already configured explicitly is never duplicated by a direct-source definition,
    so the same public page is fetched through one source identity and one result.
    """
    explicit = list(settings.sources)
    explicit_urls = {_canonical_url(source.url) for source in explicit}
    merged_categories: dict[str, list[Category]] = {}
    for category_name, urls in settings.direct_sources.items():
        category = Category(category_name)
        for raw_url in urls:
            url = _canonical_url(raw_url)
            if url in explicit_urls:
                continue
            categories = merged_categories.setdefault(url, [])
            if category not in categories:
                categories.append(category)
    derived = [
        SourceDefinition(
            id=f"direct-{_hash(url)[:40]}",
            name=urlsplit(url).hostname or url,
            url=url,
            kind="web",
            categories=categories,
            source_type="official",
        )
        for url, categories in merged_categories.items()
    ]
    return [*explicit, *derived]


def source_config_hash(source: SourceDefinition) -> str:
    """Representation identity: URL, kind, extraction selectors, and noise patterns.

    Soft rules are deliberately excluded so rule edits can reprocess already fetched raw
    content without a network request or a new representation.
    """
    payload = {
        "version": 1,
        "url": source.url,
        "kind": source.kind,
        "include_selectors": list(source.include_selectors),
        "exclude_selectors": list(source.exclude_selectors),
        "ignore_patterns": list(source.ignore_patterns),
    }
    return _hash(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _content_hash(item: ParsedItem) -> str:
    return _hash(json.dumps(
        [item.title, item.content, item.url], ensure_ascii=False, separators=(",", ":")
    ))


def _annotate(source: SourceDefinition, entry: SourceEntry) -> SourceEntry:
    """Tag/deprioritize/review an already persisted raw observation; never drop it."""
    matches: list[RuleMatch] = []
    priority = 0
    needs_review = False
    values = {"title": entry.title, "content": entry.content, "url": entry.url}
    for rule in source.rules:
        try:
            matched = re.search(rule.pattern, values[rule.field], re.IGNORECASE | re.MULTILINE)
        except re.error:  # Stored definitions are validated; a stale row must not stop a scan.
            continue
        if not matched:
            continue
        matches.append(RuleMatch(rule_id=rule.id, field=rule.field, action=rule.action, label=rule.label))
        if rule.action == "deprioritize":
            priority -= 10
        elif rule.action == "review":
            needs_review = True
            priority += 5
        else:
            priority += 10
    bounded = max(-1000, min(1000, priority))
    if entry.rule_matches == matches and entry.priority == bounded and entry.needs_review == needs_review:
        return entry
    return entry.model_copy(
        update={"rule_matches": matches, "priority": bounded, "needs_review": needs_review}
    )


def _rules_changed(source: SourceDefinition, entries: Sequence[SourceEntry]) -> list[SourceEntry]:
    return [
        after
        for before, after in ((entry, _annotate(source, entry)) for entry in entries)
        if after is not before
    ]


class SourcePipeline:
    """Run-scoped source collection cache shared across categories.

    One source is fetched at most once per run, even when it belongs to several categories.
    Due times, conditional validators, and cached observations also survive across runs.
    """

    def __init__(self, settings: Settings, repository: Repository) -> None:
        self.settings = settings
        self.repository = repository
        self._run_id = ""
        self._cache: dict[str, SourceScan] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # -- lifecycle ---------------------------------------------------------

    def begin_run(self, run_id: str = "") -> None:
        if run_id and run_id != self._run_id:
            self.reset()
        self._run_id = run_id

    def reset(self) -> None:
        self._cache.clear()
        self._locks.clear()

    def definitions(self) -> list[SourceDefinition]:
        return self.repository.list_source_definitions(configured_sources(self.settings))

    # -- collection --------------------------------------------------------

    async def collect(
        self,
        category: Category,
        fetch: FetchCallback,
        *,
        run_id: str = "",
    ) -> SourceScan:
        if run_id and run_id != self._run_id:
            self.begin_run(run_id)
        scan = SourceScan()
        now = utc_now()
        try:
            definitions = self.definitions()
        except Exception as error:  # noqa: BLE001 - isolate source configuration failure
            scan.failures.append(f"无法读取来源配置：{error}")
            return scan

        seen_entries: set[tuple[str, str]] = set()
        seen_snapshots: set[str] = set()
        for source in definitions:
            scan.notes.extend(self._review_notes(source, now))
            if not source.enabled:
                scan.notes.append(f"来源「{source.name}」已禁用，未采集；重新启用后需等待其检查间隔。")
                continue
            if category not in source.categories:
                continue
            lock = self._locks.setdefault(source.id, asyncio.Lock())
            async with lock:
                cached = self._cache.get(source.id)
                if cached is None:
                    cached = await self._collect_source(source, fetch, run_id, now)
                    self._cache[source.id] = cached
                else:
                    scan.notes.append(f"同一次运行内共享来源「{source.name}」的采集结果。")
                self._merge(scan, cached, seen_entries, seen_snapshots)
        return scan

    @staticmethod
    def _merge(
        target: SourceScan,
        outcome: SourceScan,
        seen_entries: set[tuple[str, str]],
        seen_snapshots: set[str],
    ) -> None:
        for entry in outcome.entries:
            key = (entry.source_id, entry.external_id)
            if key not in seen_entries:
                seen_entries.add(key)
                target.entries.append(entry)
        for snapshot in outcome.snapshots:
            if snapshot.id not in seen_snapshots:
                seen_snapshots.add(snapshot.id)
                target.snapshots.append(snapshot)
        target.notes.extend(outcome.notes)
        target.failures.extend(outcome.failures)

    def _review_notes(self, source: SourceDefinition, now: datetime) -> list[str]:
        notes: list[str] = []
        if source.review_reason:
            notes.append(f"来源「{source.name}」待复核：{source.review_reason}")
        if source.reopen_if:
            notes.append(f"来源「{source.name}」重新启用/复核条件：{source.reopen_if}")
        if source.checked_on is not None:
            due = datetime.combine(
                source.checked_on, datetime.min.time(), tzinfo=UTC
            ) + timedelta(seconds=source.interval_seconds)
            if now >= due:
                notes.append(
                    f"来源「{source.name}」复核已到期（上次复核 {source.checked_on.isoformat()}）。"
                )
        return notes

    def _due(self, source: SourceDefinition, state: SourceState | None, now: datetime) -> bool:
        if state is None or state.last_checked_at is None:
            return True
        if state.config_hash != source_config_hash(source):
            # An edited URL/kind/selector set is a new representation: never skip it and
            # never send validators that belong to the old representation.
            return True
        if state.next_check_at is not None:
            return now >= state.next_check_at
        interval = timedelta(seconds=source.interval_seconds)
        return now >= state.last_checked_at + interval

    def _stored_scan(
        self,
        source: SourceDefinition,
        state: SourceState,
        *,
        reason: str,
    ) -> SourceScan:
        notes = [reason]
        if state.status == "error" and state.error:
            notes.append(f"来源「{source.name}」上次采集失败，保留最近成功数据：{state.error}")
        if state.coverage_warning:
            notes.append(f"来源「{source.name}」覆盖提示：{state.coverage_warning}")
        if state.next_check_at is not None:
            notes.append(f"来源「{source.name}」下次采集时间：{state.next_check_at.isoformat()}")
        entries = list(self.repository.list_source_entries(source.id, limit=MAX_ENTRIES_PER_SOURCE))
        changed = _rules_changed(source, entries)
        if changed:
            persisted = self._persist_annotations(source, state, entries)
            if persisted is not None:
                entries = persisted
                notes.append(f"来源「{source.name}」规则已重新应用。")
        snapshots: list[SourceSnapshot] = []
        if state.last_snapshot_id:
            snapshot = self.repository.get_source_snapshot(state.last_snapshot_id)
            if snapshot is not None:
                snapshots.append(snapshot)
        return SourceScan(entries=entries, snapshots=snapshots, notes=notes)

    def _persist_annotations(
        self,
        source: SourceDefinition,
        state: SourceState | None,
        entries: list[SourceEntry],
    ) -> list[SourceEntry] | None:
        base = state.model_copy(deep=True) if state is not None else SourceState(source_id=source.id)
        annotated = [_annotate(source, entry) for entry in entries]
        try:
            return list(self.repository.commit_source_scan(base, annotated, None))
        except Exception:  # noqa: BLE001 - offline replay must not write partial annotations
            return None

    async def _collect_source(
        self,
        source: SourceDefinition,
        fetch: FetchCallback,
        run_id: str,
        now: datetime,
    ) -> SourceScan:
        state = self.repository.get_source_state(source.id)
        config_hash = source_config_hash(source)
        if state is not None and not self._due(source, state, now):
            return self._stored_scan(
                source,
                state,
                reason=(
                    f"来源「{source.name}」未到检查间隔，沿用有效缓存观察"
                    f"（间隔 {source.interval_seconds} 秒）。"
                ),
            )

        headers: dict[str, str] = {}
        if state is not None and state.config_hash == config_hash:
            if state.etag:
                headers["If-None-Match"] = state.etag
            if state.last_modified:
                headers["If-Modified-Since"] = state.last_modified

        try:
            page = await fetch(source.url, headers)
        except Exception as error:  # noqa: BLE001 - one source failure must not stop the run
            return self._failure(source, state, now, f"来源「{source.name}」请求失败：{error}")

        status_code = int(getattr(page, "status_code", 200) or 200)
        if status_code == 304:
            return self._reuse_not_modified(source, state, page, config_hash, now)
        if status_code != 200:
            return self._failure(
                source, state, now, f"来源「{source.name}」返回 HTTP {status_code}，保留最近成功状态。"
            )

        final_url = str(getattr(page, "url", "") or source.url)
        raw_content = str(getattr(page, "raw_content", "") or "")
        content_type = str(getattr(page, "content_type", "") or "")
        page_text = str(getattr(page, "text", "") or "")
        if not raw_content:
            raw_content = page_text
        if not raw_content.strip():
            return self._failure(source, state, now, f"来源「{source.name}」返回空正文，保留最近成功状态。")

        try:
            parsed = self._parse(source, raw_content, final_url, content_type, page)
        except Exception as error:  # noqa: BLE001 - malformed external content is source-local
            return self._failure(
                source,
                state,
                now,
                f"来源「{source.name}」解析失败（未删除旧条目）：{error}",
            )

        items = self._cap_items(parsed.items)
        notes: list[str] = [f"来源「{source.name}」采集成功（{source.kind}）。"]
        warning = parsed.coverage_warning
        omitted = len(self._unique_items(parsed.items)) - len(items)
        if omitted > 0:
            cap_note = (
                f"来源返回条目超过单源上限 {MAX_ENTRIES_PER_SOURCE}，"
                f"已显式截断 {omitted} 条。"
            )
            warning = f"{warning}；{cap_note}" if warning else cap_note
        entries = [_annotate(source, entry) for entry in self._entries(source, items, run_id)]
        notes.extend(self._rule_notes(entries))

        previous = self._previous_snapshot(state, config_hash, final_url)
        normalized_hash = self._normalized_hash(parsed.text, parsed.links)
        if previous is not None and previous.raw_hash == _hash(raw_content) and (
            previous.normalized_hash == normalized_hash
        ):
            snapshot = previous
            notes.append("原文与规范化正文均未变化，复用已有快照。")
            persisted_snapshot: SourceSnapshot | None = None
        else:
            snapshot = self._snapshot(
                source, previous, final_url, raw_content, content_type, parsed.text,
                parsed.links, normalized_hash, config_hash, run_id,
            )
            persisted_snapshot = snapshot
            if previous is None:
                notes.append("首次成功采集或表示配置变化，本次快照作为新基线。")

        new_state = SourceState(
            source_id=source.id,
            last_checked_at=now,
            last_success_at=now,
            status="ok",
            error="",
            etag=str(getattr(page, "etag", "") or ""),
            last_modified=str(getattr(page, "last_modified", "") or ""),
            last_snapshot_id=snapshot.id,
            config_hash=config_hash,
            entry_count=len(entries),
            window_oldest=self._window_oldest(items),
            coverage_warning=warning,
            next_check_at=now + timedelta(seconds=source.interval_seconds),
        )
        try:
            persisted = self.repository.commit_source_scan(new_state, entries, persisted_snapshot)
        except Exception as error:  # noqa: BLE001 - preserve the last good source state
            return self._failure(
                source, state, now, f"来源「{source.name}」写入失败，保留旧状态：{error}"
            )
        return SourceScan(
            entries=list(persisted),
            snapshots=[snapshot],
            notes=[*notes, *self._coverage_notes(source, warning)],
        )

    def _parse(
        self,
        source: SourceDefinition,
        raw_content: str,
        final_url: str,
        content_type: str,
        page: FetchedPage,
    ):
        if source.kind == "feed":
            return parse_feed(raw_content, final_url, content_type)
        if source.kind == "catalog":
            return parse_catalog(raw_content, final_url)
        return parse_web(
            raw_content,
            final_url,
            content_type=content_type,
            include_selectors=list(source.include_selectors),
            exclude_selectors=list(source.exclude_selectors),
            ignore_patterns=list(source.ignore_patterns),
            fallback_links=list(getattr(page, "links", []) or []),
        )

    @staticmethod
    def _unique_items(items: Sequence[ParsedItem]) -> list[ParsedItem]:
        unique: dict[str, ParsedItem] = {}
        for item in items:
            unique.setdefault(item.external_id, item)
        return list(unique.values())

    @classmethod
    def _cap_items(cls, items: list[ParsedItem]) -> list[ParsedItem]:
        return cls._unique_items(items)[:MAX_ENTRIES_PER_SOURCE]

    @staticmethod
    def _entries(
        source: SourceDefinition, items: Sequence[ParsedItem], run_id: str
    ) -> list[SourceEntry]:
        return [
            SourceEntry(
                source_id=source.id,
                external_id=item.external_id,
                url=item.url,
                title=item.title,
                content=item.content,
                published_at=item.published_at,
                content_hash=_content_hash(item),
                raw_content=item.raw_content,
                run_id=run_id,
            )
            for item in items
        ]

    @staticmethod
    def _rule_notes(entries: Sequence[SourceEntry]) -> list[str]:
        matched = [entry for entry in entries if entry.rule_matches]
        review = [entry for entry in entries if entry.needs_review]
        notes: list[str] = []
        if matched:
            notes.append(f"软规则命中 {len(matched)} 条原始条目（仅标注、降权或待看，不丢弃）。")
        if review:
            notes.append(f"{len(review)} 条原始条目待人工复核。")
        return notes

    @staticmethod
    def _normalized_hash(text: str, links: list[str]) -> str:
        return _hash(json.dumps({"text": text, "links": links}, ensure_ascii=False))

    @staticmethod
    def _window_oldest(items: Sequence[ParsedItem]) -> datetime | None:
        dates = [item.published_at for item in items if item.published_at is not None]
        return min(dates) if dates else None

    def _previous_snapshot(
        self, state: SourceState | None, config_hash: str, final_url: str
    ) -> SourceSnapshot | None:
        if state is None or not state.last_snapshot_id:
            return None
        previous = self.repository.get_source_snapshot(state.last_snapshot_id)
        if previous is None:
            return None
        if previous.config_hash != config_hash or previous.url != final_url:
            # Never compare two different representations as if one replaced the other.
            return None
        return previous

    def _snapshot(
        self,
        source: SourceDefinition,
        previous: SourceSnapshot | None,
        final_url: str,
        raw_content: str,
        content_type: str,
        text: str,
        links: list[str],
        normalized_hash: str,
        config_hash: str,
        run_id: str,
    ) -> SourceSnapshot:
        added: list[str] = []
        removed: list[str] = []
        diff = ""
        if previous is not None:
            added, removed = link_changes(previous.links, links)
            diff = text_diff(previous.text, text)
        return SourceSnapshot(
            source_id=source.id,
            url=final_url,
            raw_content=raw_content,
            content_type=content_type,
            text=text,
            links=links,
            raw_hash=_hash(raw_content),
            normalized_hash=normalized_hash,
            config_hash=config_hash,
            previous_id=previous.id if previous is not None else None,
            text_diff=diff,
            added_links=added,
            removed_links=removed,
            run_id=run_id,
        )

    @staticmethod
    def _coverage_notes(source: SourceDefinition, warning: str) -> list[str]:
        if not warning:
            return []
        return [f"来源「{source.name}」覆盖提示：{warning}"]

    def _reuse_not_modified(
        self,
        source: SourceDefinition,
        state: SourceState | None,
        page: FetchedPage,
        config_hash: str,
        now: datetime,
    ) -> SourceScan:
        if state is None or not state.last_snapshot_id:
            return self._failure(
                source, state, now, f"来源「{source.name}」返回 304，但没有可复用的成功原文快照。"
            )
        snapshot = self.repository.get_source_snapshot(state.last_snapshot_id)
        if snapshot is None:
            return self._failure(
                source, state, now, f"来源「{source.name}」返回 304，但已保存快照缺失。"
            )
        final_url = str(getattr(page, "url", "") or "")
        if snapshot.config_hash != config_hash or snapshot.url != final_url:
            return self._failure(
                source,
                state,
                now,
                f"来源「{source.name}」返回 304，但校验器对应的原文/最终地址与当前表示不一致。",
            )
        entries = list(self.repository.list_source_entries(source.id, limit=MAX_ENTRIES_PER_SOURCE))
        notes = [
            f"来源「{source.name}」返回 304，复用已保存的成功原文快照与条目。",
            *self._coverage_notes(source, state.coverage_warning),
        ]
        changed = _rules_changed(source, entries)
        if changed:
            persisted = self._persist_annotations(source, state, entries)
            if persisted is not None:
                entries = persisted
                notes.append(f"来源「{source.name}」规则已重新应用。")
        new_state = state.model_copy(
            update={
                "last_checked_at": now,
                "last_success_at": now,
                "status": "ok",
                "error": "",
                "etag": str(getattr(page, "etag", "") or "") or state.etag,
                "last_modified": str(getattr(page, "last_modified", "") or "") or state.last_modified,
                "config_hash": config_hash,
                "last_snapshot_id": snapshot.id,
                "next_check_at": now + timedelta(seconds=source.interval_seconds),
                "entry_count": len(entries),
            }
        )
        try:
            self.repository.commit_source_scan(new_state, [], None)
        except Exception as error:  # noqa: BLE001 - preserve the last good source state
            return self._failure(
                source, state, now, f"来源「{source.name}」304 状态写入失败，保留旧状态：{error}"
            )
        return SourceScan(entries=entries, snapshots=[snapshot], notes=notes)

    def _failure(
        self,
        source: SourceDefinition,
        state: SourceState | None,
        now: datetime,
        message: str,
    ) -> SourceScan:
        """Record health failure while retaining last good validators, snapshot, and entries."""
        retained = state.model_copy(deep=True) if state is not None else SourceState(source_id=source.id)
        retained.last_checked_at = now
        retained.status = "error"
        retained.error = message
        retained.next_check_at = now + timedelta(seconds=source.interval_seconds)
        try:
            self.repository.commit_source_scan(retained, [], None)
        except Exception as error:  # noqa: BLE001 - report storage failure without losing the error
            message = f"{message}（错误状态也未能保存：{error}）"
        try:
            entries = list(
                self.repository.list_source_entries(source.id, limit=MAX_ENTRIES_PER_SOURCE)
            )
        except Exception:  # noqa: BLE001 - best-effort cached entries after a source failure
            entries = []
        notes = [message]
        if entries:
            notes.append(f"来源「{source.name}」保留 {len(entries)} 条最近成功原始条目。")
        return SourceScan(entries=entries, notes=notes, failures=[message])

    # -- offline rule replay ----------------------------------------------

    def replay_rules(self, source_id: str) -> list[SourceEntry]:
        """Re-apply stored soft rules without any network access or content revision bump."""
        definitions = {source.id: source for source in self.definitions()}
        source = definitions.get(source_id)
        if source is None:
            raise LookupError(f"unknown source: {source_id}")
        state = self.repository.get_source_state(source_id)
        entries = list(self.repository.list_source_entries(source_id, limit=MAX_ENTRIES_PER_SOURCE))
        annotated = [_annotate(source, entry) for entry in entries]
        base = state.model_copy(deep=True) if state is not None else SourceState(source_id=source_id)
        return list(self.repository.commit_source_scan(base, annotated, None))


__all__ = [
    "MAX_ENTRIES_PER_SOURCE",
    "SourcePipeline",
    "SourceScan",
    "configured_sources",
    "source_config_hash",
]