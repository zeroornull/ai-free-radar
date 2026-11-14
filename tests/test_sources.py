"""Behavioral tests for managed sources, safe parsing, snapshots, and offline rules.

No test performs network I/O; every fetch is a deterministic injected fake.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from aifreeradar.config import Settings, load_config_document
from aifreeradar.models import (
    Category,
    SourceDefinition,
    SourceRule,
    SourceState,
    utc_now,
)
from aifreeradar.settings_store import SettingsStore
from aifreeradar.source_parsing import parse_feed
from aifreeradar.sources import SourcePipeline, configured_sources, source_config_hash
from aifreeradar.storage import Repository


@dataclass
class Page:
    url: str
    text: str = ""
    raw_content: str = ""
    content_type: str = "text/html"
    links: list[str] = field(default_factory=list)
    status_code: int = 200
    etag: str = ""
    last_modified: str = ""
    fetched_at: datetime = field(default_factory=utc_now)


class Fetcher:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def __call__(self, url: str, headers: dict[str, str]) -> Page:
        self.calls.append((url, dict(headers)))
        if not self.responses:
            raise AssertionError("unexpected fetch")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, Page)
        return response


def make_source(source_id: str = "src", **overrides: object) -> SourceDefinition:
    values: dict[str, object] = {
        "id": source_id,
        "name": "示例来源",
        "url": "https://example.com/page",
        "kind": "web",
        "categories": [Category.TEXT],
    }
    values.update(overrides)
    return SourceDefinition.model_validate(values)


def force_due(repository: Repository, source_id: str) -> None:
    state = repository.get_source_state(source_id)
    assert state is not None
    repository.commit_source_scan(
        state.model_copy(
            update={
                "last_checked_at": utc_now() - timedelta(days=2),
                "next_check_at": utc_now() - timedelta(seconds=1),
            }
        ),
        [],
        None,
    )


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    return Repository(tmp_path / "data")


def test_configured_sources_are_deterministic_and_merge_direct_categories() -> None:
    settings = Settings(
        direct_sources={
            "text": ["https://example.com/feed"],
            "image": ["https://example.com/feed", "https://images.example.com/"],
        },
        sources=[
            SourceDefinition(
                id="explicit",
                name="显式来源",
                url="https://explicit.example.com/",
                kind="feed",
                categories=[Category.TEXT],
            )
        ],
    )

    first = configured_sources(settings)
    second = configured_sources(settings)

    assert [source.id for source in first] == [source.id for source in second]
    assert first[0].id == "explicit"
    assert len({source.url for source in first}) == len(first)
    feed = next(source for source in first if source.url == "https://example.com/feed")
    assert feed.kind == "web"
    assert feed.id.startswith("direct-")
    assert feed.categories == [Category.TEXT, Category.IMAGE]


def test_direct_url_already_configured_explicitly_is_not_duplicated() -> None:
    explicit = SourceDefinition(
        id="explicit",
        name="显式来源",
        url="https://example.com/feed",
        categories=[Category.TEXT],
    )
    settings = Settings(
        sources=[explicit],
        direct_sources={"image": ["https://example.com/feed"]},
    )

    configured = configured_sources(settings)

    assert [source.id for source in configured] == ["explicit"]


def test_toml_sources_and_gap_limit_are_validated(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(  # noqa: FLY002 - readable TOML fixture
            [
                'model = "openai:gpt-4.1-mini"',
                "gap_search_limit = 2",
                "[[sources]]",
                'id = "feed"',
                'name = "官方动态"',
                'url = "https://example.com/feed.xml"',
                'kind = "feed"',
                'categories = ["text"]',
                "",
            ]
        ),
        encoding="utf-8",
    )

    _, _, settings = load_config_document(path)

    assert settings.gap_search_limit == 2
    assert settings.sources[0].id == "feed"
    assert settings.sources[0].kind == "feed"

    path.write_text(
        'model = "openai:gpt-4.1-mini"\ngap_search_limit = 5\n', encoding="utf-8"
    )
    with pytest.raises(ValidationError):
        load_config_document(path)


def test_settings_store_accepts_sources_and_gap_limit(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "data")
    settings = Settings(data_dir=tmp_path / "data")
    store = SettingsStore(repository, settings, {})
    payload = make_source("stored-source").model_dump(mode="json")

    updated = store.update({"sources": [payload], "gap_search_limit": 1}, {}, store.version)

    assert updated.gap_search_limit == 1
    assert updated.sources[0].id == "stored-source"
    assert store.effective().sources[0].id == "stored-source"
    with pytest.raises(ValidationError):
        store.update({"gap_search_limit": 5}, {}, store.version)


async def test_web_collection_keeps_raw_and_selected_text(repository: Repository) -> None:
    source = make_source(include_selectors=["article"], interval_seconds=3600)
    repository.save_source_definition(source)
    html = (
        "<html><head><title>免费额度页</title></head><body>"
        "<article><h1>免费额度</h1><p>每月 100 次</p>"
        "<a href='/docs'>文档</a></article><script>bad()</script></body></html>"
    )
    fetcher = Fetcher([
        Page(url=source.url, raw_content=html, content_type="text/html", etag='"v1"')
    ])
    pipeline = SourcePipeline(Settings(), repository)

    scan = await pipeline.collect(Category.TEXT, fetcher, run_id="run-1")

    assert scan.failures == []
    assert len(scan.entries) == 1
    entry = scan.entries[0]
    assert entry.external_id == source.url
    assert "免费额度" in entry.content
    assert "bad()" not in entry.content
    assert entry.url == source.url
    snapshot = scan.snapshots[0]
    assert "bad()" in snapshot.raw_content
    assert "bad()" not in snapshot.text
    assert snapshot.links == ["https://example.com/docs"]
    state = repository.get_source_state(source.id)
    assert state is not None
    assert state.status == "ok"
    assert state.etag == '"v1"'

    second = await pipeline.collect(Category.TEXT, fetcher, run_id="run-2")

    assert len(fetcher.calls) == 1
    assert second.failures == []
    assert [item.external_id for item in second.entries] == [entry.external_id]
    assert "未到检查间隔" in " ".join(second.notes)


async def test_changed_representation_refetches_without_old_validators(
    repository: Repository,
) -> None:
    source = make_source(interval_seconds=3600)
    repository.save_source_definition(source)
    pipeline = SourcePipeline(Settings(), repository)
    first_fetch = Fetcher([
        Page(url=source.url, raw_content="<article>旧正文</article>", etag='"v1"')
    ])
    first = await pipeline.collect(Category.TEXT, first_fetch, run_id="run-1")
    old_snapshot_id = first.snapshots[0].id

    edited = source.model_copy(update={"include_selectors": ["main"]})
    repository.save_source_definition(edited)
    force_due(repository, source.id)
    second_fetch = Fetcher([
        Page(url=source.url, raw_content="<main>新正文</main>", etag='"v2"')
    ])

    second = await SourcePipeline(Settings(), repository).collect(
        Category.TEXT, second_fetch, run_id="run-2"
    )

    assert second.failures == []
    assert second_fetch.calls[0][1] == {}
    assert second.snapshots[0].previous_id is None
    assert second.snapshots[0].id != old_snapshot_id
    assert second.snapshots[0].config_hash == source_config_hash(edited)
    assert second.entries[0].revision == 2


async def test_not_modified_reuses_successful_snapshot(repository: Repository) -> None:
    source = make_source(interval_seconds=3600)
    repository.save_source_definition(source)
    pipeline = SourcePipeline(Settings(), repository)
    success = await pipeline.collect(
        Category.TEXT,
        Fetcher([Page(url=source.url, raw_content="<article>稳定正文</article>", etag='"v1"')]),
        run_id="run-1",
    )
    snapshot_id = success.snapshots[0].id
    force_due(repository, source.id)

    fetcher = Fetcher([Page(url=source.url, status_code=304, raw_content="", text="")])
    reused = await SourcePipeline(Settings(), repository).collect(
        Category.TEXT, fetcher, run_id="run-2"
    )

    assert reused.failures == []
    assert fetcher.calls[0][1] == {"If-None-Match": '"v1"'}
    assert [item.id for item in reused.snapshots] == [snapshot_id]
    assert len(repository.list_source_snapshots(source.id)) == 1
    assert "304" in " ".join(reused.notes)


async def test_not_modified_without_snapshot_is_failure(repository: Repository) -> None:
    source = make_source("no-snapshot", interval_seconds=3600)
    repository.save_source_definition(source)
    repository.commit_source_scan(
        SourceState(
            source_id=source.id,
            last_checked_at=utc_now() - timedelta(days=2),
            next_check_at=utc_now() - timedelta(seconds=1),
            config_hash=source_config_hash(source),
            etag='"lost"',
        ),
        [],
        None,
    )

    scan = await SourcePipeline(Settings(), repository).collect(
        Category.TEXT,
        Fetcher([Page(url=source.url, status_code=304)]),
        run_id="run-1",
    )

    assert scan.failures
    assert "缺少" in scan.failures[0] or "没有可复用" in scan.failures[0]
    state = repository.get_source_state(source.id)
    assert state is not None
    assert state.status == "error"


async def test_selector_miss_keeps_old_entries_and_reports_health_failure(
    repository: Repository,
) -> None:
    source = make_source(include_selectors=["article"], interval_seconds=3600)
    repository.save_source_definition(source)
    pipeline = SourcePipeline(Settings(), repository)
    first = await pipeline.collect(
        Category.TEXT,
        Fetcher([Page(url=source.url, raw_content="<article>旧正文</article>", etag='"v1"')]),
        run_id="run-1",
    )
    old_snapshot = first.snapshots[0]
    broken = source.model_copy(update={"include_selectors": ["main.missing"]})
    repository.save_source_definition(broken)

    scan = await SourcePipeline(Settings(), repository).collect(
        Category.TEXT,
        Fetcher([Page(url=source.url, raw_content="<article>新正文</article>")]),
        run_id="run-2",
    )

    assert scan.failures
    assert "解析失败" in scan.failures[0]
    assert [item.external_id for item in scan.entries] == [first.entries[0].external_id]
    state = repository.get_source_state(source.id)
    assert state is not None
    assert state.status == "error"
    assert state.last_snapshot_id == old_snapshot.id
    assert state.etag == '"v1"'


async def test_feed_entries_keep_native_ids_window_and_revisions(
    repository: Repository,
) -> None:
    source = make_source(
        "feed-source",
        url="https://example.com/feed.xml",
        kind="feed",
        interval_seconds=3600,
    )
    repository.save_source_definition(source)
    first_feed = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item><guid>guid-1</guid><link>/one</link><title>免费试用</title>
        <description>old trial</description>
        <pubDate>Tue, 01 Jan 2025 00:00:00 GMT</pubDate></item>
    </channel></rss>"""
    pipeline = SourcePipeline(Settings(), repository)
    first = await pipeline.collect(
        Category.TEXT,
        Fetcher([Page(url=source.url, raw_content=first_feed, content_type="application/rss+xml")]),
        run_id="run-1",
    )

    assert first.failures == []
    entry = first.entries[0]
    assert entry.external_id == "guid-1"
    assert entry.url == "https://example.com/one"
    assert entry.published_at is not None
    assert entry.revision == 1
    state = repository.get_source_state(source.id)
    assert state is not None
    assert "当前发布窗口" in state.coverage_warning

    force_due(repository, source.id)
    second_feed = first_feed.replace("old trial", "new trial")
    second = await SourcePipeline(Settings(), repository).collect(
        Category.TEXT,
        Fetcher([Page(url=source.url, raw_content=second_feed, content_type="application/rss+xml")]),
        run_id="run-2",
    )

    assert second.entries[0].id == entry.id
    assert second.entries[0].revision == 2
    assert "new trial" in second.entries[0].content
    assert second.snapshots[0].text_diff


def test_feed_parses_atom_and_json_feed_and_rejects_entities() -> None:
    atom = """<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><id>urn:entry:1</id><title>Atom</title>
      <link rel="alternate" href="/atom"/>
      <updated>2025-01-02T03:04:05Z</updated>
      <content>正文</content></entry></feed>"""
    parsed_atom = parse_feed(atom, "https://example.com/feed")
    assert parsed_atom.items[0].external_id == "urn:entry:1"
    assert parsed_atom.items[0].url == "https://example.com/atom"

    parsed_json = parse_feed(
        json.dumps(
            {
                "version": "https://jsonfeed.org/version/1.1",
                "items": [
                    {
                        "id": "json-1",
                        "url": "https://example.com/json",
                        "title": "JSON",
                        "content_text": "JSON 正文",
                        "date_published": "2025-01-03T00:00:00Z",
                    }
                ],
            }
        ),
        "https://example.com/feed.json",
        "application/feed+json",
    )
    assert parsed_json.items[0].external_id == "json-1"
    assert parsed_json.items[0].published_at is not None

    with pytest.raises(ValueError, match="DTD"):
        parse_feed(
            '<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rss/>',
            "https://example.com/feed",
        )


async def test_soft_rules_annotate_replay_without_network_or_revision(
    repository: Repository,
) -> None:
    source = make_source(
        "rules-source",
        url="https://example.com/feed.json",
        kind="feed",
        interval_seconds=3600,
        rules=[
            SourceRule(id="tag", field="title", pattern="免费", action="tag", label="免费线索"),
            SourceRule(id="review", field="content", pattern="trial", action="review", label="待看"),
        ],
    )
    repository.save_source_definition(source)
    feed = json.dumps(
        {"items": [{"id": "entry-1", "url": "https://example.com/a", "title": "免费试用", "content_text": "trial quota"}]}
    )
    fetcher = Fetcher([
        Page(url=source.url, raw_content=feed, content_type="application/feed+json")
    ])
    pipeline = SourcePipeline(Settings(), repository)
    first = await pipeline.collect(Category.TEXT, fetcher, run_id="run-1")

    entry = first.entries[0]
    assert {match.rule_id for match in entry.rule_matches} == {"tag", "review"}
    assert entry.priority > 0
    assert entry.needs_review is True
    assert entry.revision == 1

    edited = source.model_copy(
        update={
            "rules": [
                SourceRule(id="down", field="content", pattern="trial", action="deprioritize", label="降权")
            ]
        }
    )
    repository.save_source_definition(edited)
    replayed = pipeline.replay_rules(source.id)

    assert replayed[0].id == entry.id
    assert replayed[0].revision == 1
    assert replayed[0].priority == -10
    assert replayed[0].needs_review is False
    assert [match.label for match in replayed[0].rule_matches] == ["降权"]
    assert len(fetcher.calls) == 1


async def test_catalog_changes_are_leads_not_free_proof(repository: Repository) -> None:
    source = make_source(
        "catalog-source",
        url="https://catalog.example.com/api.json",
        kind="catalog",
        source_type="catalog",
        interval_seconds=3600,
    )
    repository.save_source_definition(source)
    catalog = {
        "providers": {
            "acme": {
                "name": "Acme",
                "doc": "https://acme.example.com/docs",
                "models": {
                    "m1": {
                        "name": "M1",
                        "cost": {"input": 0, "output": 0},
                    }
                },
            }
        }
    }

    scan = await SourcePipeline(Settings(), repository).collect(
        Category.TEXT,
        Fetcher([
            Page(
                url=source.url,
                raw_content=json.dumps(catalog),
                content_type="application/json",
            )
        ]),
        run_id="run-1",
    )

    assert scan.failures == []
    ids = {entry.external_id for entry in scan.entries}
    assert ids == {"provider:acme", "model:acme:m1"}
    model = next(entry for entry in scan.entries if entry.external_id == "model:acme:m1")
    assert "价格为零也不证明免费" in model.content
    assert '"input": 0' in model.raw_content
    state = repository.get_source_state(source.id)
    assert state is not None
    assert "零价格不证明免费" in state.coverage_warning


async def test_same_source_is_shared_across_categories_within_a_run(
    repository: Repository,
) -> None:
    source = make_source(
        "multi",
        categories=[Category.TEXT, Category.IMAGE],
        interval_seconds=3600,
    )
    repository.save_source_definition(source)
    fetcher = Fetcher([Page(url=source.url, raw_content="<article>共享正文</article>")])
    pipeline = SourcePipeline(Settings(), repository)

    first = await pipeline.collect(Category.TEXT, fetcher, run_id="shared-run")
    force_due(repository, source.id)
    second = await pipeline.collect(Category.IMAGE, fetcher, run_id="shared-run")

    assert first.failures == [] and second.failures == []
    assert len(fetcher.calls) == 1
    assert "共享" in " ".join(second.notes)
    assert [item.external_id for item in second.entries] == [
        item.external_id for item in first.entries
    ]


async def test_fetch_failure_retains_last_good_state_and_entries(
    repository: Repository,
) -> None:
    source = make_source("failure", interval_seconds=3600)
    repository.save_source_definition(source)
    pipeline = SourcePipeline(Settings(), repository)
    first = await pipeline.collect(
        Category.TEXT,
        Fetcher([Page(url=source.url, raw_content="<article>好正文</article>", etag='"good"')]),
        run_id="run-1",
    )
    force_due(repository, source.id)

    failed = await SourcePipeline(Settings(), repository).collect(
        Category.TEXT,
        Fetcher([RuntimeError("network down")]),
        run_id="run-2",
    )

    assert failed.failures
    assert [item.external_id for item in failed.entries] == [first.entries[0].external_id]
    state = repository.get_source_state(source.id)
    assert state is not None
    assert state.status == "error"
    assert state.etag == '"good"'
    assert state.last_snapshot_id == first.snapshots[0].id
    assert state.last_success_at is not None


async def test_disabled_and_expired_review_sources_are_explicit(
    repository: Repository,
) -> None:
    source = make_source(
        "disabled",
        enabled=False,
        checked_on=date.today() - timedelta(days=2),
        interval_seconds=60,
        review_reason="域名归属待确认",
        reopen_if="官方域名确认后重新启用",
    )
    repository.save_source_definition(source)
    fetcher = Fetcher([])

    scan = await SourcePipeline(Settings(), repository).collect(
        Category.TEXT, fetcher, run_id="run-1"
    )

    assert fetcher.calls == []
    joined = " ".join(scan.notes)
    assert "已禁用" in joined
    assert "域名归属待确认" in joined
    assert "复核已到期" in joined
    assert "官方域名确认后重新启用" in joined


async def test_entry_cap_is_reported_as_coverage_warning(
    repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("aifreeradar.sources.MAX_ENTRIES_PER_SOURCE", 2)
    source = make_source(
        "cap",
        url="https://example.com/feed.json",
        kind="feed",
        interval_seconds=3600,
    )
    repository.save_source_definition(source)
    feed = json.dumps(
        {
            "items": [
                {"id": f"item-{index}", "url": f"https://example.com/{index}", "title": "条目"}
                for index in range(3)
            ]
        }
    )

    scan = await SourcePipeline(Settings(), repository).collect(
        Category.TEXT,
        Fetcher([
            Page(url=source.url, raw_content=feed, content_type="application/feed+json")
        ]),
        run_id="run-1",
    )

    assert len(scan.entries) == 2
    state = repository.get_source_state(source.id)
    assert state is not None
    assert "显式截断 1 条" in state.coverage_warning
    assert "显式截断" in " ".join(scan.notes)