"""Source management API and SPA deep-link regression tests (isolated temp data)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from filelock import FileLock

from aifreeradar.config import Settings
from aifreeradar.models import (
    Category,
    ResearchBatch,
    ResearchTrace,
    Run,
    SourceDefinition,
    SourceEntry,
    SourceRule,
    SourceSnapshot,
    SourceState,
    utc_now,
)
from aifreeradar.web import _is_page, create_app

ENTRY_ROUTES = ("/sources", "/settings", "/sources/feed-main")


class Researcher:
    """Research double: any collection call records itself and returns nothing."""

    def __init__(self) -> None:
        self.calls: list[object] = []

    async def research(self, scope, existing):
        self.calls.append(scope)
        return ResearchBatch()


def source_settings(tmp_path, definitions: list[SourceDefinition]) -> Settings:
    return Settings(
        data_dir=tmp_path,
        schedule_enabled=False,
        sources=list(definitions),
    )


def feed_definition(**overrides) -> SourceDefinition:
    payload = {
        "id": "feed-main",
        "name": "官方更新日志",
        "url": "https://example.com/feed.xml",
        "kind": "feed",
        "categories": [Category.TEXT],
        "interval_seconds": 3600,
    }
    payload.update(overrides)
    return SourceDefinition.model_validate(payload)


def source_state(source_id: str) -> SourceState:
    now = datetime(2026, 1, 2, 8, 0, tzinfo=UTC)
    return SourceState(
        source_id=source_id,
        status="ok",
        last_checked_at=now,
        last_success_at=now,
        etag='"v1"',
        config_hash="config-1",
        entry_count=0,
        next_check_at=now + timedelta(hours=1),
    )


def source_entry(source_id: str, external_id: str, title: str, **overrides) -> SourceEntry:
    payload = {
        "source_id": source_id,
        "external_id": external_id,
        "url": f"https://example.com/{external_id}",
        "title": title,
        "content": f"{title} 的正文",
        "raw_content": f"<p>{title}</p>",
        "content_hash": f"hash-{external_id}",
    }
    payload.update(overrides)
    return SourceEntry.model_validate(payload)


def source_snapshot(
    source_id: str,
    *,
    raw: str,
    text: str,
    previous_id: str | None = None,
    added: list[str] | None = None,
    removed: list[str] | None = None,
    diff: str = "",
) -> SourceSnapshot:
    return SourceSnapshot(
        source_id=source_id,
        url="https://example.com/feed.xml",
        raw_content=raw,
        content_type="application/rss+xml",
        text=text,
        links=["https://example.com/one"],
        raw_hash=f"raw-{raw}",
        normalized_hash=f"normalized-{text}",
        config_hash="config-1",
        previous_id=previous_id,
        text_diff=diff,
        added_links=list(added or []),
        removed_links=list(removed or []),
    )


def test_sources_list_reports_configured_definitions_without_state(tmp_path):
    definition = feed_definition()
    app = create_app(source_settings(tmp_path, [definition]), researcher=Researcher())
    with TestClient(app) as client:
        response = client.get("/api/sources")
        assert response.status_code == 200
        body = response.json()
    assert [item["definition"]["id"] for item in body] == [definition.id]
    assert body[0]["definition"]["kind"] == "feed"
    assert body[0]["definition"]["enabled"] is True
    assert body[0]["state"] is None


def test_source_editor_fields_persist_and_reopen_without_network(tmp_path):
    definition = feed_definition()
    researcher = Researcher()
    app = create_app(source_settings(tmp_path, [definition]), researcher=researcher)
    edited = definition.model_copy(
        update={
            "name": "官方更新日志（审阅）",
            "kind": "catalog",
            "categories": [Category.TEXT, Category.IMAGE],
            "source_type": "official",
            "official_domain": "example.com",
            "enabled": False,
            "interval_seconds": 7200,
            "include_selectors": ["main article", "h2"],
            "exclude_selectors": ["nav"],
            "ignore_patterns": ["^广告"],
            "rules": [
                SourceRule(
                    id="rule-1",
                    field="title",
                    pattern="限时",
                    action="review",
                    label="限时活动",
                )
            ],
            "checked_on": date(2026, 1, 2),
            "review_reason": "官方目录结构调整",
            "reopen_if": "恢复公开目录后重新启用",
        }
    )
    with TestClient(app) as client:
        saved = client.put(
            f"/api/sources/{definition.id}", json=edited.model_dump(mode="json")
        )
        assert saved.status_code == 200, saved.text
        payload = saved.json()["definition"]
        assert payload["name"] == "官方更新日志（审阅）"
        assert payload["kind"] == "catalog"
        assert payload["enabled"] is False
        assert payload["interval_seconds"] == 7200
        assert payload["include_selectors"] == ["main article", "h2"]
        assert payload["exclude_selectors"] == ["nav"]
        assert payload["ignore_patterns"] == ["^广告"]
        assert payload["review_reason"] == "官方目录结构调整"
        assert payload["reopen_if"] == "恢复公开目录后重新启用"
        assert payload["checked_on"] == "2026-01-02"
        assert [rule["action"] for rule in payload["rules"]] == ["review"]
        assert researcher.calls == []
    # A new process reloads the stored override, so the form can be reopened as saved.
    reopened = create_app(source_settings(tmp_path, [definition]), researcher=researcher)
    with TestClient(reopened) as client:
        listed = client.get("/api/sources").json()
    assert len(listed) == 1
    assert listed[0]["definition"]["name"] == "官方更新日志（审阅）"
    assert listed[0]["definition"]["kind"] == "catalog"
    assert listed[0]["definition"]["enabled"] is False
    assert researcher.calls == []


def test_source_save_rejects_mismatched_identity_and_invalid_source_input(tmp_path):
    definition = feed_definition()
    app = create_app(source_settings(tmp_path, [definition]), researcher=Researcher())
    body = definition.model_dump(mode="json")
    with TestClient(app) as client:
        mismatch = dict(body, id="another-source")
        response = client.put("/api/sources/feed-main", json=mismatch)
        assert response.status_code == 422
        assert response.json()["detail"]

        invalid_url = dict(body, url="javascript:alert(1)")
        response = client.put("/api/sources/feed-main", json=invalid_url)
        assert response.status_code == 422

        invalid_regex = dict(
            body,
            rules=[
                {"id": "bad-rule", "field": "title", "pattern": "(", "action": "tag", "label": "坏规则"}
            ],
        )
        response = client.put("/api/sources/feed-main", json=invalid_regex)
        assert response.status_code == 422

        invalid_selector = dict(
            body,
            include_selectors=["article["],
        )
        response = client.put("/api/sources/feed-main", json=invalid_selector)
        assert response.status_code == 422

        unknown = dict(body, id="missing-source")
        response = client.put("/api/sources/missing-source", json=unknown)
        assert response.status_code == 404
        assert response.json()["detail"]


def test_source_entries_paginate_and_unknown_sources_are_404(tmp_path):
    definition = feed_definition()
    app = create_app(source_settings(tmp_path, [definition]), researcher=Researcher())
    repository = app.state.repository
    entries = [
        source_entry(definition.id, "item-0", "条目零"),
        source_entry(definition.id, "item-1", "条目一", priority=1),
        source_entry(definition.id, "item-2", "条目二"),
    ]
    repository.commit_source_scan(source_state(definition.id), entries)
    with TestClient(app) as client:
        first = client.get(f"/api/sources/{definition.id}/entries?limit=2")
        assert first.status_code == 200
        assert len(first.json()) == 2
        second = client.get(f"/api/sources/{definition.id}/entries?limit=2&offset=2")
        assert second.status_code == 200
        combined = {item["external_id"] for item in first.json() + second.json()}
        assert combined == {"item-0", "item-1", "item-2"}
        assert all(item["raw_content"] for item in first.json())

        assert client.get(f"/api/sources/{definition.id}/entries?limit=0").status_code == 422
        assert client.get(f"/api/sources/{definition.id}/entries?offset=-1").status_code == 422
        missing = client.get("/api/sources/missing-source/entries")
        assert missing.status_code == 404
        assert missing.json()["detail"]


def test_source_snapshots_list_detail_and_first_baseline(tmp_path):
    definition = feed_definition()
    app = create_app(source_settings(tmp_path, [definition]), researcher=Researcher())
    repository = app.state.repository
    baseline = source_snapshot(definition.id, raw="<rss>v1</rss>", text="第一条正文")
    repository.commit_source_scan(
        source_state(definition.id), [source_entry(definition.id, "item-0", "条目零")], baseline
    )
    follow_up = source_snapshot(
        definition.id,
        raw="<rss>v2</rss>",
        text="第二条正文",
        previous_id=baseline.id,
        added=["https://example.com/two"],
        removed=["https://example.com/old"],
        diff="+ 第二条正文",
    )
    repository.commit_source_scan(
        source_state(definition.id), [source_entry(definition.id, "item-1", "条目一")], follow_up
    )
    with TestClient(app) as client:
        listed = client.get(f"/api/sources/{definition.id}/snapshots")
        assert listed.status_code == 200
        snapshots = listed.json()
        assert {item["id"] for item in snapshots} == {baseline.id, follow_up.id}

        detail = client.get(f"/api/source-snapshots/{follow_up.id}")
        assert detail.status_code == 200
        snapshot = detail.json()
        assert snapshot["previous_id"] == baseline.id
        assert snapshot["text_diff"] == "+ 第二条正文"
        assert snapshot["added_links"] == ["https://example.com/two"]
        assert snapshot["removed_links"] == ["https://example.com/old"]
        assert snapshot["raw_content"] == "<rss>v2</rss>"

        baseline_detail = client.get(f"/api/source-snapshots/{baseline.id}").json()
        assert baseline_detail["previous_id"] is None

        assert client.get("/api/sources/missing-source/snapshots").status_code == 404
        missing = client.get("/api/source-snapshots/missing-snapshot")
        assert missing.status_code == 404
        assert missing.json()["detail"]


def test_replay_reapplies_rules_to_stored_entries_without_network(tmp_path):
    definition = feed_definition(
        rules=[
            {
                "id": "rule-review",
                "field": "title",
                "pattern": "限时",
                "action": "review",
                "label": "限时活动",
            }
        ]
    )
    researcher = Researcher()
    app = create_app(source_settings(tmp_path, [definition]), researcher=researcher)
    app.state.repository.commit_source_scan(
        source_state(definition.id),
        [source_entry(definition.id, "item-0", "限时试用 100 次")],
    )
    with TestClient(app) as client:
        replayed = client.post(f"/api/sources/{definition.id}/replay")
        assert replayed.status_code == 200, replayed.text
        entries = replayed.json()
        assert len(entries) == 1
        assert entries[0]["needs_review"] is True
        assert entries[0]["rule_matches"] == [
            {
                "rule_id": "rule-review",
                "field": "title",
                "action": "review",
                "label": "限时活动",
            }
        ]
        stored = client.get(f"/api/sources/{definition.id}/entries").json()
        assert stored[0]["rule_matches"][0]["rule_id"] == "rule-review"
        assert stored[0]["revision"] == 1

        assert client.post("/api/sources/missing-source/replay").status_code == 404
    assert researcher.calls == []


def test_source_writes_conflict_with_active_run_and_foreign_process_lock(tmp_path):
    definition = feed_definition()
    app = create_app(source_settings(tmp_path, [definition]), researcher=Researcher())
    body = definition.model_dump(mode="json")
    with TestClient(app) as client:
        app.state.manager._active = Run(id="active-run", status="running")
        try:
            busy = client.put(f"/api/sources/{definition.id}", json=body)
            assert busy.status_code == 409
            assert busy.json()["detail"]
            replay = client.post(f"/api/sources/{definition.id}/replay")
            assert replay.status_code == 409
            assert client.get(f"/api/sources/{definition.id}/entries").status_code == 200
        finally:
            app.state.manager._active = None

        lock = FileLock(tmp_path / "research.lock")
        lock.acquire(timeout=0)
        try:
            blocked = client.put(f"/api/sources/{definition.id}", json=body)
            assert blocked.status_code == 409
            assert blocked.json()["detail"]
        finally:
            lock.release()

        allowed = client.put(f"/api/sources/{definition.id}", json=body)
        assert allowed.status_code == 200


def test_run_detail_copies_research_traces_for_gap_queries_and_stop_reasons(tmp_path):
    definition = feed_definition()
    app = create_app(source_settings(tmp_path, [definition]), researcher=Researcher())
    trace = ResearchTrace(
        gap_id="gap-1",
        category=Category.TEXT,
        query="example.com free trial credits",
        goal="确认免费额度",
        trigger_url="https://example.com/pricing",
        source_ids=[definition.id],
        result_urls=["https://example.com/docs/limits"],
        new_evidence_urls=["https://example.com/docs/limits"],
        stop_reason="budget_exhausted",
        search_calls=1,
        observed_at=utc_now(),
    )
    run = Run(
        id="run-traces",
        trigger="manual",
        status="partial",
        started_at=utc_now(),
        finished_at=utc_now(),
        notes=["检索预算已用尽"],
        research_traces=[trace],
    )
    app.state.repository.save_run(run)
    with TestClient(app) as client:
        detail = client.get("/api/tasks/run-traces")
        assert detail.status_code == 200
        traces = detail.json()["run"]["research_traces"]
        assert traces[0]["gap_id"] == "gap-1"
        assert traces[0]["goal"] == "确认免费额度"
        assert traces[0]["trigger_url"] == "https://example.com/pricing"
        assert traces[0]["result_urls"] == ["https://example.com/docs/limits"]
        assert traces[0]["stop_reason"] == "budget_exhausted"

        listed = client.get("/api/tasks").json()
        assert [item["id"] for item in listed] == ["run-traces"]
        assert listed[0]["research_traces"][0]["stop_reason"] == "budget_exhausted"


def test_sources_and_settings_are_spa_deep_links(tmp_path):
    for path in ENTRY_ROUTES:
        assert _is_page(path), path
    assert not _is_page("/sources/one/two")

    definition = feed_definition()
    app = create_app(source_settings(tmp_path, [definition]), researcher=Researcher())
    with TestClient(app) as client:
        for path in ("/sources", "/settings"):
            response = client.get(path)
            # Without a built SPA the host reports 503; it must never be a routed 404.
            assert response.status_code in {200, 503}, path
            if response.status_code == 503:
                assert "前端尚未构建" in response.text


def test_app_labels_expose_access_modes(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, schedule_enabled=False), researcher=Researcher())
    with TestClient(app) as client:
        labels = client.get("/api/app").json()["labels"]
    assert labels["api"] == "API 可调用"
    assert labels["product"] == "产品内额度（非 API）"
    assert labels["unknown"] == "入口未核实"