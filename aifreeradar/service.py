"""Single-writer research lifecycle and durable Markdown task results."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, TypeGuard, cast
from uuid import uuid4

from filelock import FileLock, Timeout

from .briefing import markdown_text, render_briefing
from .models import (
    Category,
    CollectedMessage,
    NewsItem,
    Policy,
    ResearchBatch,
    Resource,
    Run,
    RunStats,
    Scope,
)

if TYPE_CHECKING:
    from .config import Settings
    from .settings_store import SettingsStore
    from .storage import Repository

TriggerName = Literal["manual", "scheduled", "catchup"]


def _known_trigger(value: str) -> TypeGuard[TriggerName]:
    return value in {"manual", "scheduled", "catchup"}



class Researcher(Protocol):
    async def research(self, scope: Scope, existing: list[Resource]) -> ResearchBatch: ...


class SourceResearcher(Researcher, Protocol):
    async def collect_sources(self, resources: list[Resource]) -> ResearchBatch: ...


class BusyError(RuntimeError):
    """Another task owns the research records and Memory directory."""


class TaskManager:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        researcher: Researcher | None = None,
        *,
        settings_store: SettingsStore | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self._researcher = researcher
        self._injected_researcher = researcher
        self._settings_store = settings_store
        self._run_settings: Settings | None = None
        self._active: Run | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock: FileLock | None = None
        self._closed = False

    @property
    def active(self) -> Run | None:
        return self._active.model_copy(deep=True) if self._active is not None else None

    async def start(
        self,
        scope: Scope,
        trigger: str = "manual",
        schedule_day: str | None = None,
    ) -> Run:
        """Persist a running task before scheduling its nonblocking execution."""
        if self._closed:
            raise RuntimeError("任务管理器已关闭")
        if self._active is not None:
            raise BusyError("已有研究任务运行中，请等待完成后再试")
        if not _known_trigger(trigger):
            raise ValueError("未知任务触发方式")
        if trigger == "manual" and schedule_day is not None:
            raise ValueError("手动任务不能修改每日定时执行记录")
        if trigger != "manual" and schedule_day is None:
            raise ValueError("定时或补跑任务必须指定计划日期")
        if schedule_day is not None:
            datetime.strptime(schedule_day, "%Y-%m-%d")
        run_settings = (
            self._settings_store.effective()
            if self._settings_store is not None
            else self.settings
        ).model_copy(deep=True)
        data_dir = Path(run_settings.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        lock = FileLock(data_dir / "research.lock")
        try:
            lock.acquire(timeout=0)
        except Timeout as exc:
            raise BusyError("另一进程正在研究，资源库与 Memory 暂不可写入") from exc
        try:
            # Recheck under the cross-process lock, after any competing run finished.
            if schedule_day is not None and self.repository.schedule_completed(schedule_day):
                raise BusyError("该日期的定时研究已经完成")
            self._run_settings = run_settings
            run = Run(
                id=uuid4().hex,
                trigger=trigger,
                scope=scope.model_copy(deep=True),
                status="running",
                started_at=datetime.now(UTC),
                schedule_day=schedule_day,
            )
            self.repository.save_run(run)
            self._active = run
            self._lock = lock
            coroutine = self._execute(run)
            try:
                self._task = asyncio.create_task(coroutine, name=f"research-{run.id}")
                self._task.add_done_callback(lambda task: self._task_finished(run, task))
            except BaseException:
                coroutine.close()
                run.status = "failed"
                run.error = "无法启动后台研究任务"
                try:
                    self._finish(run, [], [run.error])
                finally:
                    self._active = None
                    self._lock = None
                raise
            return run.model_copy(deep=True)
        except BaseException:
            self._run_settings = None
            lock.release()
            raise

    async def wait_idle(self) -> None:
        task = self._task
        if task is not None:
            # Cancelling a waiting HTTP request must not cancel the research task.
            await asyncio.shield(asyncio.gather(task, return_exceptions=True))

    async def close(self) -> None:
        self._closed = True
        task = self._task
        if task is not None and not task.done():
            task.cancel()
        await self.wait_idle()

    def _task_finished(self, run: Run, task: asyncio.Task[None]) -> None:
        # A task cancelled before its first event-loop turn never enters its
        # coroutine's finally block. Its completion callback owns that cleanup.
        if not task.cancelled():
            task.exception()
        if self._active is not run:
            return
        failures = ["应用关闭或任务被取消，本次研究尚未开始"]
        run.status = "failed"
        existing: list[Resource] = []
        try:
            try:
                ignored = self.repository.ignored_ids()
                existing = [
                    resource
                    for resource in self.repository.list_resources()
                    if run.scope.includes(resource) and resource.id not in ignored
                ]
                if run.scope.resource_ids:
                    expected = [
                        resource for resource in existing if resource.status in {"active", "pending"}
                    ]
                    self._record_unfinished(run, expected, failures)
            except Exception as exc:  # noqa: BLE001
                failures.append(self._redact(f"读取历史记录失败：{type(exc).__name__}：{exc}"))
            self._attach_traces(run)
            self._finish(run, existing, failures)
        finally:
            self._release_writer()

    def _settings_snapshot(self) -> Settings:
        return self._run_settings if self._run_settings is not None else self.settings

    def _redact(self, value: str) -> str:
        active = self._settings_snapshot()
        names = {
            active.model_api_key_env,
            active.search_api_key_env,
        }
        names.update(
            name
            for name in os.environ
            if any(part in name.upper() for part in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))
        )
        secrets = sorted(
            {os.environ[name] for name in names if name and os.environ.get(name)},
            key=len,
            reverse=True,
        )
        for secret in secrets:
            value = value.replace(secret, "[已隐藏凭据]")
        value = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[已隐藏凭据]", value)
        value = re.sub(r"(?i)(https?://)[^\s/@]+:[^\s/@]+@", r"\1[已隐藏凭据]@", value)
        return value

    def _redact_value(self, value: object) -> object:
        if isinstance(value, str):
            return self._redact(value)
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._redact_value(item) for key, item in value.items()}
        return value

    def _redact_message(self, message: CollectedMessage) -> CollectedMessage:
        return CollectedMessage.model_validate(self._redact_value(message.model_dump()))

    def _attach_traces(self, run: Run) -> None:
        """Copy and redact the run's gap ledger, including failed or cancelled segments."""
        researcher = self._researcher
        traces = getattr(researcher, "last_research_traces", None) if researcher is not None else None
        if not isinstance(traces, list):
            return
        run.research_traces = [
            type(trace).model_validate(self._redact_value(trace.model_dump()))
            for trace in traces
        ]

    def _attach_run_id(self, run: Run) -> None:
        setter = getattr(self._researcher, "set_run_id", None) if self._researcher else None
        if callable(setter):
            setter(run.id)

    def _incomplete(self, resource: Resource, reason: str) -> Policy:
        values = resource.model_dump(include=set(Policy.model_fields))
        values.update(
            resource_id=resource.id,
            check_status="incomplete",
            failure_reason=self._redact(reason),
        )
        return Policy.model_validate(values)

    def _mark_missing(self, run: Run, expected: list[Resource], reason: str) -> list[str]:
        missing: list[Policy] = []
        failures: list[str] = []
        for previous in expected:
            current = self.repository.get_resource(previous.id)
            if current is not None and current.last_task_id == run.id:
                continue
            missing.append(self._incomplete(previous, reason))
            failures.append(f"{previous.provider} / {previous.service}：{reason}")
        if missing:
            self.repository.apply_batch(ResearchBatch(resources=missing), run, datetime.now(UTC))
        return failures

    async def _execute(self, run: Run) -> None:
        existing: list[Resource] = []
        expected: list[Resource] = []
        failures: list[str] = []
        try:
            # Explicit structured history is the source of truth, independently of Memory.
            ignored = self.repository.ignored_ids()
            existing = [
                resource
                for resource in self.repository.list_resources()
                if run.scope.includes(resource) and resource.id not in ignored
            ]
            if run.scope.resource_ids:
                expected = [
                    resource for resource in existing if resource.status in {"active", "pending"}
                ]
            if self._researcher is None:
                # Construct only after acquiring research.lock: Memory may write on init.
                from .research import HarnessResearcher

                self._researcher = HarnessResearcher(self._settings_snapshot())
            self._attach_run_id(run)
            researched = await self._researcher.research(
                run.scope.model_copy(deep=True), existing
            )
            try:
                discoveries = list(getattr(self._researcher, "last_discoveries", []))
                self.repository.record_discoveries(run.id, discoveries)
            except Exception as exc:  # noqa: BLE001
                failures.append(self._redact(f"保存发现来源失败：{type(exc).__name__}：{exc}"))
            batch = ResearchBatch.model_validate(researched)
            self._attach_stats(run)
            self._attach_traces(run)
            batch.failures = [self._redact(reason) for reason in batch.failures]
            batch.notes = [self._redact(note) for note in batch.notes]
            for policy in batch.resources:
                policy.failure_reason = self._redact(policy.failure_reason)
            failures.extend(batch.failures)
            if batch.resources:
                # Injected providers may still return strict policy output. Production
                # collection returns messages and never turns history into rechecks.
                failures.extend(
                    f"{policy.provider} / {policy.service}：{policy.failure_reason or '本次核查未完成'}"
                    for policy in batch.resources
                    if run.scope.includes(policy) and policy.check_status != "success"
                )
                self.repository.apply_batch(batch, run, datetime.now(UTC))
                for resource in self.repository.list_resources():
                    if (
                        resource.last_task_id == run.id
                        and resource.id not in ignored
                        and run.scope.includes(resource)
                        and resource.check_status != "success"
                    ):
                        failures.append(
                            f"{resource.provider} / {resource.service}："
                            f"{resource.failure_reason or '本次核查未完成'}"
                        )
            if not run.scope.resource_ids:
                messages = [
                    message
                    for message in batch.messages
                    if run.scope.includes(message.policy)
                    and message.policy.resource_id not in ignored
                ]
                batch.messages = [self._redact_message(message) for message in messages]
                self.repository.apply_messages(batch, run, datetime.now(UTC))
            # Identity/source rejection can append failures during persistence.
            failures.extend(self._redact(reason) for reason in batch.failures)
            if run.scope.resource_ids:
                failures.extend(self._mark_missing(run, expected, "研究结果未返回该资源的复查结论"))
            run.notes = [self._redact(note) for note in batch.notes]
            run.status = "partial" if failures else "success"
            await self._translate_collected(run, ignored)
        except asyncio.CancelledError:
            run.status = "failed"
            failures.append("应用关闭或任务被取消，本次研究未完成；保留上次已确认结论")
            self._attach_stats(run)
            self._attach_traces(run)
            self._record_unfinished(run, expected, failures)
        except Exception as exc:  # noqa: BLE001
            run.status = "failed"
            failures.append(self._redact(f"{type(exc).__name__}：{exc}"))
            self._attach_stats(run)
            self._attach_traces(run)
            self._record_unfinished(run, expected, failures)
        finally:
            try:
                self._finish(run, existing, failures)
            finally:
                self._release_writer()

    async def _translate_collected(self, run: Run, ignored: set[str]) -> None:
        """Additive zh pass after persistence; translation problems never fail collection."""
        try:
            from .translation import ModelTranslator, translate_message, translate_resource_failure

            translator = ModelTranslator(self._settings_snapshot())
            events = [
                event
                for event in self.repository.list_messages(task_id=run.id, include_ended=True)
                if event.resource_id not in ignored and run.scope.includes(event.policy)
            ]
            resource_ids = {event.resource_id for event in events}
            resource_ids.update(
                resource.id
                for resource in self.repository.list_resources()
                if resource.last_task_id == run.id
                and resource.id not in ignored
                and run.scope.includes(resource)
            )
            translated_events = [await translate_message(translator, event) for event in events]
            self.repository.save_news_translations(translated_events)
            for resource_id in sorted(resource_ids):
                resource = self.repository.get_resource(resource_id)
                if resource is None:
                    continue
                messages = [
                    await translate_message(translator, message) for message in resource.messages
                ]
                self.repository.save_message_translations(resource_id, messages)
                self.repository.save_resource_translations(
                    [await translate_resource_failure(translator, resource)]
                )
        except Exception as exc:  # noqa: BLE001
            run.notes.append(self._redact(f"机器翻译未完成，保留原文：{type(exc).__name__}"))

    async def backfill_sources(self) -> Run:
        """Recover local historical sources, then search only records still missing them."""
        return await self._start_backfill(sources=True)

    async def backfill_translations(self) -> Run:
        """Translate stored English descriptive text under the same single-writer lock."""
        return await self._start_backfill(sources=False)

    async def _start_backfill(self, *, sources: bool) -> Run:
        label = "来源" if sources else "译文"
        if self._closed:
            raise BusyError(f"任务管理器已关闭，无法回填{label}")
        if self._active is not None:
            raise BusyError("已有研究任务运行中，请等待完成后再试")
        run_settings = (
            self._settings_store.effective()
            if self._settings_store is not None
            else self.settings
        ).model_copy(deep=True)
        data_dir = Path(run_settings.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        lock = FileLock(data_dir / "research.lock")
        try:
            lock.acquire(timeout=0)
        except Timeout as exc:
            raise BusyError("另一进程正在研究，资源库与 Memory 暂不可写入") from exc
        try:
            self._run_settings = run_settings
            run = Run(
                id=uuid4().hex,
                trigger="manual",
                scope=Scope(categories=list(Category), region="global"),
                status="running",
                started_at=datetime.now(UTC),
                stats=RunStats() if sources else None,
            )
            self.repository.save_run(run)
            self._active = run
            self._lock = lock
            coroutine = self._execute_source_backfill(run) if sources else self._execute_backfill(run)
            try:
                self._task = asyncio.create_task(coroutine, name=f"backfill-{run.id}")
                self._task.add_done_callback(lambda task: self._backfill_finished(run, task, label))
            except BaseException:
                coroutine.close()
                run.status = "failed"
                run.error = f"无法启动{label}回填任务"
                try:
                    self._finish_backfill(run, [run.error])
                finally:
                    self._active = None
                    self._lock = None
                raise
            return run.model_copy(deep=True)
        except BaseException:
            self._run_settings = None
            lock.release()
            raise

    def _source_targets(self) -> list[Resource]:
        ignored = self.repository.ignored_ids()
        return [
            resource for resource in self.repository.list_resources()
            if resource.id not in ignored
            and not any(message.sources for message in resource.messages)
        ]

    async def _execute_source_backfill(self, run: Run) -> None:
        failures: list[str] = []
        searched = False
        recovered = 0
        imported = 0
        run.stats = RunStats()
        try:
            recovered = self.repository.recover_legacy_messages()
            targets = self._source_targets()
            if targets:
                if self._researcher is None:
                    from .research import HarnessResearcher

                    self._researcher = HarnessResearcher(self._settings_snapshot())
                self._attach_run_id(run)
                searched = True
                result = await cast(SourceResearcher, self._researcher).collect_sources(targets)
                batch = ResearchBatch.model_validate(result)
                self._attach_stats(run)
                self._attach_traces(run)
                run.notes.extend(self._redact(note) for note in batch.notes)
                failures.extend(self._redact(reason) for reason in batch.failures)
                target_ids = {resource.id for resource in targets}
                messages = [
                    self._redact_message(message) for message in batch.messages
                    if message.policy.resource_id in target_ids
                ]
                events = (
                    self.repository.import_legacy_messages(messages, run) if messages else []
                )
                imported = len({event.resource_id for event in events})
                if messages:
                    # Import keeps the historical timestamp and policy verification separate.
                    await self._translate_collected(run, self.repository.ignored_ids())
            run.status = "partial" if failures else "success"
        except asyncio.CancelledError:
            run.status = "failed"
            failures.append("应用关闭或任务被取消，来源回填未完成；已恢复的历史消息保留")
        except Exception as exc:  # noqa: BLE001
            run.status = "failed"
            failures.append(self._redact(f"{type(exc).__name__}：{exc}"))
        finally:
            try:
                if searched:
                    self._attach_stats(run)
                    self._attach_traces(run)
                remaining = len(self._source_targets())
                run.notes.append(
                    f"来源回填：本地恢复 {recovered} 条，补搜恢复 {imported} 条；"
                    f"仍有 {remaining} 条历史线索·来源待补。未说明的政策条件不影响收录。"
                )
                self._finish_backfill(run, failures)
            finally:
                self._release_writer()

    def _release_writer(self) -> None:
        self._active = None
        lock, self._lock = self._lock, None
        if lock is not None:
            lock.release()
        self._run_settings = None
        self._researcher = self._injected_researcher

    async def _execute_backfill(self, run: Run) -> None:
        failures: list[str] = []
        updated = 0
        try:
            from .translation import ModelTranslator, translate_message, translate_resource_failure

            translator = ModelTranslator(self._settings_snapshot())
            resources, events = self.repository.translation_records()
            translated_events: list[NewsItem] = []
            for event in events:
                translated = await translate_message(translator, event)
                if translated is not event:
                    updated += 1
                    translated_events.append(translated)
            self.repository.save_news_translations(translated_events)
            for resource in resources:
                messages: list[CollectedMessage] = []
                for message in resource.messages:
                    translated = await translate_message(translator, message)
                    if translated is not message:
                        updated += 1
                    messages.append(translated)
                self.repository.save_message_translations(resource.id, messages)
                translated_resource = await translate_resource_failure(translator, resource)
                if translated_resource is not resource:
                    updated += 1
                self.repository.save_resource_translations([translated_resource])
            run.status = "success"
            run.notes = [f"译文回填完成：更新 {updated} 条记录（机器翻译，未经核验）"]
        except asyncio.CancelledError:
            run.status = "failed"
            failures.append("应用关闭或任务被取消，译文回填未完成")
        except Exception as exc:  # noqa: BLE001
            run.status = "failed"
            failures.append(self._redact(f"{type(exc).__name__}：{exc}"))
        finally:
            try:
                self._finish_backfill(run, failures)
            finally:
                self._release_writer()

    def _backfill_finished(self, run: Run, task: asyncio.Task[None], label: str) -> None:
        # A task cancelled before its first turn never enters its coroutine's finally block.
        if not task.cancelled():
            task.exception()
        if self._active is not run:
            return
        run.status = "failed"
        try:
            self._finish_backfill(run, [f"应用关闭或任务被取消，{label}回填尚未开始"])
        finally:
            self._release_writer()

    def _finish_backfill(self, run: Run, failures: list[str]) -> None:
        run.finished_at = datetime.now(UTC)
        run.error = "；".join(dict.fromkeys(self._redact(reason) for reason in failures))
        if run.error and run.status == "success":
            run.status = "partial"
        self.repository.save_run(run)

    def _attach_stats(self, run: Run) -> None:
        researcher = self._researcher
        stats = getattr(researcher, "last_stats", None) if researcher is not None else None
        if isinstance(stats, RunStats):
            run.stats = stats.model_copy(deep=True)

    def _record_unfinished(self, run: Run, expected: list[Resource], failures: list[str]) -> None:
        if not run.scope.resource_ids:
            return
        try:
            failures.extend(self._mark_missing(run, expected, "研究中断，本次复查未完成"))
        except Exception as exc:  # noqa: BLE001
            failures.append(self._redact(f"保存未完成核查失败：{type(exc).__name__}：{exc}"))

    def _finish(self, run: Run, existing: list[Resource], failures: list[str]) -> None:
        failures = list(dict.fromkeys(self._redact(reason) for reason in failures))
        run.finished_at = datetime.now(UTC)
        run.error = "；".join(failures)
        try:
            ignored = self.repository.ignored_ids()
            resources = [
                resource
                for resource in self.repository.list_resources()
                if run.scope.includes(resource) and resource.id not in ignored
            ]
            changes = [
                change
                for change in self.repository.get_changes(run.id)
                if change.resource_id not in ignored
            ]
            try:
                discoveries = self.repository.discoveries_for_run(run.id)
            except Exception as exc:  # noqa: BLE001
                failures.append(self._redact(f"读取发现来源失败：{type(exc).__name__}：{exc}"))
                discoveries = []
            messages = [
                message
                for message in self.repository.list_messages(task_id=run.id, include_ended=True)
                if message.resource_id not in ignored and run.scope.includes(message.policy)
            ]
            if failures and run.status == "success":
                run.status = "partial"
            run.error = "；".join(failures)
            markdown = render_briefing(
                run, resources, changes, failures, discoveries, messages=messages
            )
        except Exception as exc:  # noqa: BLE001
            run.status = "failed"
            failures.append(self._redact(f"生成简报失败：{type(exc).__name__}：{exc}"))
            run.error = "；".join(failures)
            markdown = self._failure_markdown(run, existing, failures)
        try:
            run.briefing_path = str(self._save_briefing(run.id, self._redact(markdown)))
        except Exception as exc:  # noqa: BLE001
            run.status = "failed"
            run.error = self._redact(
                f"{run.error}；保存简报失败：{type(exc).__name__}：{exc}"
            ).strip("；")
        self.repository.save_run(run)

    def _save_briefing(self, run_id: str, markdown: str) -> Path:
        directory = Path(self._settings_snapshot().data_dir) / "briefings"
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{run_id}.md"
        temporary = directory / f".{run_id}.{uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(markdown)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def _failure_markdown(self, run: Run, existing: list[Resource], failures: list[str]) -> str:
        trigger = {"manual": "手动", "scheduled": "定时", "catchup": "补跑"}[run.trigger]
        lines = [
            f"# 免费 AI API 简报 — {run.started_at.astimezone():%Y-%m-%d %H:%M}",
            "",
            f"- 任务：{run.id}",
            f"- 研究范围：{', '.join(run.scope.categories)}；{run.scope.region}",
            f"- 触发方式：{trigger}",
            "- 执行结果：失败",
            "- 说明：来源消息收集 / 按需政策核验；未实测调用；网络访问未实测",
            "",
            "本次无新增或变化。研究未完成，不代表现有政策已经失效。",
            "",
            "## 核查失败 / 未完成事项",
            "",
            *(f"- {markdown_text(reason)}" for reason in failures),
        ]
        if run.scope.resource_ids:
            for resource in existing:
                if resource.status in {"active", "pending"}:
                    lines.append(
                        f"- {markdown_text(resource.provider)} / {markdown_text(resource.service)}：保留上次已确认结论"
                        f"（{resource.status}）；上次成功核查："
                        f"{resource.last_success_at.isoformat() if resource.last_success_at else '未核实'}"
                    )
        return "\n".join(lines) + "\n"
