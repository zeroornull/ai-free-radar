"""HTTP acceptance tests with real lifespan, SQLite, files, and injected research."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aifreeradar.api_models import ResourceDetailRead, TaskDetailRead
from aifreeradar.config import Settings
from aifreeradar.models import (
    UNKNOWN,
    Category,
    CollectedMessage,
    Evidence,
    MessageSource,
    Policy,
    ResearchBatch,
    ResourceStatus,
    Run,
    RunStats,
    Scope,
)
from aifreeradar.storage import Repository
from aifreeradar.web import create_app

CHECKED = datetime(2026, 11, 1, 1, tzinfo=UTC)


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.text = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)

    @property
    def links(self):
        return [attrs["href"] for tag, attrs in self.elements if tag == "a" and "href" in attrs]

    @property
    def inputs(self):
        return [attrs for tag, attrs in self.elements if tag in {"input", "select", "textarea"}]

    @property
    def visible(self):
        return " ".join(self.text)


def policy(service="Verified Text API", category="text", **updates):
    values = {
        "provider": "Example Provider",
        "service": service,
        "category": category,
        "provider_domain": "example.com",
        "service_key": service.casefold().replace(" ", "-"),
        "api_url": "https://example.com/api",
        "docs_url": "https://example.com/docs",
        "free_type": "ongoing",
        "quota": "1000",
        "quota_unit": "requests",
        "refresh_cycle": "monthly",
        "claim_conditions": "Free registration",
        "payment_required": False,
        "payment_method_required": False,
        "china_policy": "supported",
        "status": "active",
    }
    values.update(updates)
    fields = {
        "api_url",
        "docs_url",
        "free_type",
        "quota",
        "quota_unit",
        "refresh_cycle",
        "claim_conditions",
        "payment_required",
        "payment_method_required",
        "china_policy",
        "status",
    }
    values.setdefault(
        "evidence",
        [
            Evidence(
                field=field,
                url="https://example.com/policy",
                quote=f"Official {field} statement: {values.get(field, 'unknown')}",
                source_type="official",
                checked_at=CHECKED,
            )
            for field in sorted(fields)
        ],
    )
    return Policy(**values)


class Researcher:
    def __init__(self, *results, blocked=False):
        self.results = list(results) or [ResearchBatch()]
        self.calls = []
        self.entered = threading.Event()
        self.release = asyncio.Event()
        self.last_stats: RunStats | None = None
        if not blocked:
            self.release.set()

    async def research(self, scope, existing):
        self.calls.append((scope.model_copy(deep=True), list(existing)))
        self.entered.set()
        await self.release.wait()
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, Exception):
            raise result
        return result.model_copy(deep=True)


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, schedule_enabled=False)


def seed(repository, *policies, when=CHECKED):
    run = Run(scope=Scope(), started_at=when, status="success", finished_at=when)
    repository.save_run(run)
    repository.apply_batch(ResearchBatch(resources=list(policies)), run, when)
    return run


def wait_idle(client, app):
    client.portal.call(app.state.manager.wait_idle)


def reported_policy(service="Free Text API", category="text", **updates):
    values: dict[str, Any] = {
        "provider": "Example Provider",
        "service": service,
        "category": category,
        "provider_domain": "example.com",
        "service_key": service.casefold().replace(" ", "-"),
    }
    values.update(updates)
    return Policy(**values)


def collected_message(
    service="Free Text API",
    category="text",
    *,
    offer_key="default",
    summary="Free API tier with 1000 monthly requests and no purchase required.",
    url="https://example.com/free-api",
    excerpt="Free tier: 1000 requests per month.",
    ended=False,
    end_reason="",
    published_at=None,
):
    return CollectedMessage(
        policy=reported_policy(service, category),
        offer_key=offer_key,
        title=f"{service} 免费接口",
        summary=summary,
        sources=[
            MessageSource(
                url=url,
                title=f"{service} 官方页面",
                excerpt=f"{excerpt} {end_reason}" if ended else excerpt,
                source_type="official",
                access="page",
            )
        ],
        published_at=published_at,
        ended=ended,
        end_reason=end_reason,
    )


def collect(repository, *messages, when=CHECKED):
    categories = list({message.policy.category for message in messages})
    run = Run(
        scope=Scope(categories=categories),
        started_at=when,
        status="success",
        finished_at=when,
    )
    repository.save_run(run)
    events = repository.apply_messages(ResearchBatch(messages=list(messages)), run, when)
    return run, events


def post_run(client, categories=("text",), region="global"):
    response = client.post("/api/tasks", json={"categories": list(categories), "region": region})
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["trigger"] == "manual"
    assert "briefing_path" not in body
    return body["id"]


def resource_ids(response):
    assert response.status_code == 200, response.text
    return [resource["id"] for resource in response.json()]


@pytest.mark.parametrize("filters", [
    *[{"category": category.value} for category in Category],
    *[{"china_policy": value} for value in ("supported", "unsupported", "unknown")],
    *[{"status": value} for value in ("active", "pending", "expired")],
    {"category": "text", "china_policy": "supported", "status": "active"},
    {"category": "image", "china_policy": "supported", "status": "active"},
])
def test_resource_filters_cover_all_categories_policies_and_statuses_without_changing_defaults(settings, filters):
    researcher = Researcher()
    app = create_app(settings, researcher=researcher)
    seed(app.state.repository, policy(),
         policy("Pending Image API", "image", payment_required=None, china_policy="unknown"),
         policy("Retired Video API", "video", status="expired", china_policy="unsupported"),
         policy("Speech API", "speech", china_policy="unknown"),
         policy("Embedding API", "embedding", china_policy="unsupported"),
         policy("Rerank API", "rerank"))
    resources = app.state.repository.list_resources()
    before = settings.default_scope.model_dump()
    visible = [r for r in resources if r.status != ResourceStatus.EXPIRED]
    with TestClient(app) as client:
        for selected in (filters, {}):
            bucket = resources if selected.get("status") == "expired" else visible
            expected = [
                r.id for r in bucket
                if all(str(getattr(r, key)) == value for key, value in selected.items())
            ]
            assert resource_ids(client.get("/api/resources", params=selected)) == expected
        assert resource_ids(client.get("/api/resources?include_ended=true")) == [r.id for r in resources]
    assert settings.default_scope.model_dump() == before
    assert researcher.calls == []


def test_resource_detail_shows_evidence_changes_previous_success_and_failure(settings):
    app = create_app(settings, researcher=Researcher())
    repository = app.state.repository
    seed(repository, policy())
    original = repository.list_resources()[0]
    changed = seed(repository, policy(quota="2000"), when=CHECKED + timedelta(hours=1))
    confirmed = repository.get_resource(original.id)
    seed(repository, policy(check_status="failed", failure_reason="source temporarily unreachable"), when=CHECKED + timedelta(hours=2))
    with TestClient(app) as client:
        response = client.get(f"/api/resources/{original.id}")
        assert response.status_code == 200
        body = response.json()
        resource = body["resource"]
        assert resource["docs_url"] == "https://example.com/docs"
        assert any(item["url"] == "https://example.com/policy" for item in resource["evidence"])
        assert resource["quota"] == "2000"
        assert resource["check_status"] == "failed"
        assert resource["failure_reason"] == "source temporarily unreachable"
        assert datetime.fromisoformat(resource["last_success_at"]) == confirmed.last_success_at
        assert len(body["history"]) == 2
        change = next(item for item in body["history"] if item["task_id"] == changed.id)
        assert change["before"]["quota"] == "1000"
        assert change["after"]["quota"] == "2000"
    assert repository.get_resource(original.id).last_success_at == confirmed.last_success_at


def test_manual_http_flow_repeated_categories_unique_downloads_and_restart(settings):
    researcher = Researcher(ResearchBatch(resources=[policy(), policy("Verified Image API", "image")]))
    app = create_app(settings, researcher=researcher)
    defaults = settings.default_scope.model_dump()
    with TestClient(app) as client:
        first_id = post_run(client, ("text", "image", "text"), "china")
        wait_idle(client, app)
        first = app.state.repository.get_run(first_id)
        assert first.scope == Scope(categories=[Category.TEXT, Category.IMAGE], region="china")
        assert first.trigger == "manual" and first.status == "success"
        assert researcher.calls[0][0] == first.scope
        assert settings.default_scope.model_dump() == defaults
        task = client.get(f"/api/tasks/{first_id}").json()
        assert task["run"]["has_briefing"] is True
        assert [r["id"] for r in client.get("/api/briefings").json()] == [first_id]
        assert client.get(f"/api/briefings/{first_id}").json()["html"]
        first_download = client.get(f"/api/briefings/{first_id}/download")
        assert first_download.status_code == 200
        assert first_download.content == Path(first.briefing_path).read_bytes()
        assert first_id in first_download.text
        assert first_download.headers["content-type"].startswith("text/markdown; charset=utf-8")
        assert first_download.headers["content-disposition"] == f'attachment; filename="{first_id}.md"'
        second_id = post_run(client, ("text", "image"), "china")
        wait_idle(client, app)
        second = app.state.repository.get_run(second_id)
        assert first_id != second_id and first.briefing_path != second.briefing_path
        second_download = client.get(f"/api/briefings/{second_id}/download")
        assert second_download.content == Path(second.briefing_path).read_bytes()
        assert second_id in second_download.text and "本次无新增或变化" in second_download.text
        assert client.get(f"/api/briefings/{first_id}/download").content == first_download.content
        assert [r["id"] for r in client.get("/api/tasks").json()] == [r.id for r in app.state.repository.list_runs()]
    reopened = create_app(settings, researcher=Researcher())
    with TestClient(reopened) as client:
        assert client.get(f"/api/tasks/{first_id}").status_code == 200
        assert client.get(f"/api/briefings/{first_id}/download").content == first_download.content
        assert len(client.get("/api/resources").json()) == 2
        assert len(client.get("/api/tasks").json()) == 2


def test_busy_http_task_returns_conflict_and_does_not_spawn_another_run(settings):
    researcher = Researcher(blocked=True)
    app = create_app(settings, researcher=researcher)
    with TestClient(app) as client:
        first_id = post_run(client)
        try:
            assert researcher.entered.wait(timeout=3)
            assert client.get(f"/api/tasks/{first_id}").json()["run"]["status"] == "running"
            assert client.get("/api/app").json()["active_run"]["id"] == first_id
            response = client.post("/api/tasks", json={"categories": ["image"], "region": "china"})
            assert response.status_code == 409
            assert response.json() == {"detail": "已有研究任务运行中，当前无法发起另一项任务。查看运行中的任务，完成后再试。"}
            assert len(app.state.repository.list_runs()) == len(researcher.calls) == 1
        finally:
            assert client.portal is not None
            client.portal.call(researcher.release.set)
            wait_idle(client, app)


@pytest.mark.parametrize("result,status,reason", [
    (RuntimeError("model credentials unavailable"), "failed", "model credentials unavailable"),
    (ResearchBatch(resources=[policy()], failures=["image lookup unavailable"]), "partial", "image lookup unavailable"),
])
def test_failed_and_partial_http_tasks_have_readable_downloadable_reports(settings, result, status, reason):
    app = create_app(settings, researcher=Researcher(result))
    with TestClient(app) as client:
        task_id = post_run(client, ("text", "image"))
        wait_idle(client, app)
        task = client.get(f"/api/tasks/{task_id}").json()
        assert task["run"]["status"] == status and task["run"]["has_briefing"]
        assert reason in json.dumps(task, ensure_ascii=False)
        report = client.get(f"/api/briefings/{task_id}")
        assert report.status_code == 200 and reason in Document(report.json()["html"]).visible
        download = client.get(f"/api/briefings/{task_id}/download")
        assert download.status_code == 200 and reason in download.text
        assert task_id in [r["id"] for r in client.get("/api/briefings").json()]
        if status == "partial":
            assert client.get("/api/resources").json()[0]["status"] == "active"


@pytest.mark.parametrize("route", ["/api/resources/missing", "/api/tasks/missing", "/api/briefings/missing", "/api/briefings/missing/download", "/api/no-such-route"])
def test_missing_objects_return_404(settings, route):
    with TestClient(create_app(settings, researcher=Researcher())) as client:
        response = client.get(route)
        assert response.status_code == 404
        assert set(response.json()) == {"detail"}
        assert isinstance(response.json()["detail"], str)
        if route == "/api/no-such-route":
            assert response.json() == {"detail": "未找到此接口。"}


@pytest.mark.parametrize("data", [{}, {"categories": []}, {"categories": "text"}, {"categories": ["invalid"]}, {"categories": ["text"], "region": "invalid"}, {"categories": ["text"], "trigger": "scheduled"}])
def test_invalid_manual_scope_does_not_start_research(settings, data):
    researcher = Researcher()
    app = create_app(settings, researcher=researcher)
    with TestClient(app) as client:
        response = client.post("/api/tasks", json=data)
        assert response.status_code == 422
        assert response.json() == {"detail": "研究范围或筛选条件无效，请检查输入后重试。"}
        assert app.state.repository.list_runs() == [] and researcher.calls == []


@pytest.mark.parametrize("headers,expected", [
    ({"host": "evil.example"}, {400, 403}), ({"host": "127.0.0.1.evil.example"}, {400, 403}),
    ({"origin": "https://evil.example"}, {403}), ({"origin": "null"}, {403}),
    ({"origin": "http://testserver:18765"}, {403}), ({"sec-fetch-site": "cross-site"}, {403}),
])
def test_foreign_host_or_origin_cannot_trigger_research(settings, headers, expected):
    researcher = Researcher()
    app = create_app(settings, researcher=researcher)
    with TestClient(app) as client:
        response = client.post("/api/tasks", json={"categories": ["text"], "region": "global"}, headers=headers)
        assert response.status_code in expected
        assert app.state.repository.list_runs() == [] and researcher.calls == []


def test_same_origin_loopback_request_can_start_research(settings):
    app = create_app(settings, researcher=Researcher())
    with TestClient(app, base_url="http://127.0.0.1:18765") as client:
        response = client.post("/api/tasks", json={"categories": ["text"]}, headers={"origin": "http://127.0.0.1:18765"})
        assert response.status_code == 202
        assert response.headers["referrer-policy"] == "same-origin"
        wait_idle(client, app)
        assert len(app.state.repository.list_runs()) == 1


def test_health_and_task_form_do_not_expose_credentials_or_offer_backend_editing(settings, monkeypatch):
    settings.model_api_key_env = "AIFREE_TEST_MODEL_KEY"
    settings.search_api_key_env = "AIFREE_TEST_SEARCH_KEY"
    secrets = ["model-secret-value-unique", "search-secret-value-unique", "direct-model-secret-unique", "direct-search-secret-unique"]
    monkeypatch.setenv(settings.model_api_key_env, secrets[0])
    monkeypatch.setenv(settings.search_api_key_env, secrets[1])
    settings.model_api_key, settings.search_api_key = secrets[2:]
    app = create_app(settings, researcher=Researcher(RuntimeError(" ".join(secrets))))
    with TestClient(app) as client:
        assert set(client.get("/health").json()) == {"status", "version"}
        app_data = client.get("/api/app").json()
        assert set(app_data) == {"version", "default_scope", "schedule_enabled", "schedule_time", "active_run", "categories", "resource_statuses", "china_policies", "review_states", "open_leads", "labels"}
        assert app_data["default_scope"] == settings.default_scope.model_dump(mode="json")
        assert app_data["schedule_time"] == settings.schedule_time
        task_id = post_run(client)
        wait_idle(client, app)
        for route in ("/health", "/api/app", "/api/tasks", "/api/resources", "/api/briefings", f"/api/tasks/{task_id}", f"/api/briefings/{task_id}", f"/api/briefings/{task_id}/download"):
            response = client.get(route)
            assert response.status_code == 200
            assert all(secret not in response.text for secret in secrets)
            if route.startswith("/api") and not route.endswith("/download"):
                assert "briefing_path" not in response.text
        schema = app.openapi()
        assert "briefing_path" not in json.dumps(schema)


def test_model_strings_and_markdown_never_create_executable_html_or_unsafe_links(settings):
    script = "<script>alert('model')</script>"
    image = '<img src=x onerror="alert(1)">'
    unsafe = "javascript:alert('link')"
    malicious = policy(service=script, provider=image, docs_url=unsafe)
    malicious.evidence[0].quote = image
    app = create_app(settings, researcher=Researcher(ResearchBatch(resources=[malicious], notes=[script, image])))
    with TestClient(app) as client:
        task_id = post_run(client)
        wait_idle(client, app)
        resource = client.get("/api/resources").json()[0]
        assert resource["service"] == script and resource["provider"] == image and resource["docs_url"] == unsafe
        assert image in [item["quote"] for item in resource["evidence"]]
        assert script in client.get(f"/api/tasks/{task_id}").json()["run"]["notes"]
        run = app.state.repository.get_run(task_id)
        Path(run.briefing_path).write_text(f'# Unsafe source\n\n{script}\n\n{image}\n\n[unsafe]({unsafe})\n\n![image](https://example.com/tracker)\n\n[safe](https://example.com/docs)\n', encoding="utf-8")
        response = client.get(f"/api/briefings/{task_id}")
        assert response.status_code == 200
        document = Document(response.json()["html"])
        assert script in document.visible and image in document.visible
        assert all(tag not in {"script", "img", "iframe", "object", "embed"} for tag, _ in document.elements)
        assert all(not key.lower().startswith("on") for _, attrs in document.elements for key in attrs)
        assert all(not link.lower().startswith(("javascript:", "data:", "vbscript:")) for link in document.links)
        assert "https://example.com/docs" in document.links
        assert all(set(attrs.get("rel", "").split()) >= {"noreferrer", "noopener"} for tag, attrs in document.elements if tag == "a")


def test_download_uses_task_directory_instead_of_untrusted_saved_path(settings, tmp_path):
    app = create_app(settings, researcher=Researcher())
    foreign = tmp_path / "outside-briefing.md"
    foreign.write_text("private outside document", encoding="utf-8")
    with TestClient(app) as client:
        task_id = post_run(client)
        wait_idle(client, app)
        run = app.state.repository.get_run(task_id)
        legitimate = Path(run.briefing_path).read_bytes()
        run.briefing_path = str(foreign)
        app.state.repository.save_run(run)
        assert client.get(f"/api/tasks/{task_id}").json()["run"]["has_briefing"] is True
        response = client.get(f"/api/briefings/{task_id}/download")
        assert response.status_code == 200 and response.content == legitimate
        (settings.data_dir / "briefings" / f"{task_id}.md").unlink()
        assert client.get(f"/api/briefings/{task_id}/download").status_code == 404
        assert client.get(f"/api/briefings/{task_id}").status_code == 404
        assert client.get(f"/api/tasks/{task_id}").json()["run"]["has_briefing"] is False
        assert client.get("/api/briefings").json() == []


def test_second_app_lifespan_cannot_recover_another_apps_running_task(settings):
    researcher = Researcher(blocked=True)
    first = create_app(settings, researcher=researcher)
    second = create_app(settings, researcher=Researcher())
    with TestClient(first) as client:
        task_id = post_run(client)
        try:
            assert researcher.entered.wait(timeout=3)
            with pytest.raises(RuntimeError), TestClient(second):
                pass
            assert first.state.repository.get_run(task_id).status == "running"
            assert first.state.manager.active.id == task_id
        finally:
            assert client.portal is not None
            client.portal.call(researcher.release.set)
            wait_idle(client, first)


def test_lifespan_recovers_interrupted_record_with_schedule_disabled(settings):
    repository = Repository(settings.data_dir)
    interrupted = Run(started_at=CHECKED, scope=Scope(categories=[Category.TEXT]))
    repository.save_run(interrupted)
    researcher = Researcher()
    app = create_app(settings, researcher=researcher)
    with TestClient(app) as client:
        recovered = client.get(f"/api/tasks/{interrupted.id}").json()["run"]
        assert recovered["status"] == "failed" and recovered["finished_at"] is not None
        assert recovered["error"]
        assert researcher.calls == []


def test_task_page_and_briefing_show_consumption_stats(settings):
    researcher = Researcher()
    stats = RunStats(search_calls=3, fetch_calls=5, model_requests=2, input_tokens=100, output_tokens=20, cache_read_tokens=40, reasoning_tokens=7)
    researcher.last_stats = stats
    app = create_app(settings, researcher=researcher)
    with TestClient(app) as client:
        task_id = post_run(client)
        wait_idle(client, app)
        assert client.get(f"/api/tasks/{task_id}").json()["run"]["stats"] == stats.model_dump()
        briefing = client.get(f"/api/briefings/{task_id}").json()
        assert briefing["run"]["stats"] == stats.model_dump()
        assert "本次消耗：搜索 3 次、抓取 5 页、模型请求 2 次、输入 100 tokens、输出 20 tokens、缓存命中 40 tokens" in Document(briefing["html"]).visible
        for value in (None, RunStats()):
            run = Run(started_at=CHECKED, scope=Scope(categories=[Category.TEXT]), status="success", finished_at=CHECKED, stats=value)
            app.state.repository.save_run(run)
            assert client.get(f"/api/tasks/{run.id}").json()["run"]["stats"] == (None if value is None else value.model_dump())


@pytest.mark.parametrize("field", ["category", "china_policy", "status"])
def test_invalid_resource_filters_return_public_validation_error(settings, field):
    with TestClient(create_app(settings, researcher=Researcher())) as client:
        response = client.get("/api/resources", params={field: "invalid-secret-input"})
        assert response.status_code == 422
        assert response.json() == {"detail": "研究范围或筛选条件无效，请检查输入后重试。"}


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("origin", ["http://127.0.0.1:15173", "http://localhost:15173"])
def test_dev_origin_requires_explicit_exact_configuration(settings, monkeypatch, configured, origin):
    monkeypatch.delenv("AIFREERADAR_DEV_ORIGIN", raising=False)
    if configured:
        monkeypatch.setenv("AIFREERADAR_DEV_ORIGIN", origin)
    researcher = Researcher()
    app = create_app(settings, researcher=researcher)
    with TestClient(app, base_url="http://127.0.0.1:18765") as client:
        for rejected in ("null", "http://127.0.0.1:15174", "https://evil.example"):
            assert client.post("/api/tasks", json={"categories": ["text"]}, headers={"origin": rejected}).status_code == 403
        assert client.post("/api/tasks", json={"categories": ["text"]}, headers={"origin": origin, "sec-fetch-site": "cross-site"}).status_code == 403
        response = client.post("/api/tasks", json={"categories": ["text"]}, headers={"origin": origin})
        assert response.status_code == (202 if configured else 403)
        if configured:
            wait_idle(client, app)
        assert len(researcher.calls) == int(configured)


@pytest.mark.parametrize("origin", ["", " ", "http://localhost:15174", "https://localhost:15173", "http://127.0.0.1:15173/"])
def test_invalid_dev_origin_fails_configuration(settings, monkeypatch, origin):
    monkeypatch.setenv("AIFREERADAR_DEV_ORIGIN", origin)
    with pytest.raises(ValueError):
        create_app(settings, researcher=Researcher())


def test_recursive_presented_secrets_preserve_json_and_stored_facts(settings):
    secret = 'direct-secret-"quoted<&value'
    settings.model_api_key = secret
    app = create_app(settings, researcher=Researcher())
    run = seed(app.state.repository, policy(service=f"Service {secret}", quota=secret))
    run.error = secret
    run.notes = [secret]
    app.state.repository.save_run(run)
    resource = app.state.repository.list_resources()[0]
    # Persist an independently supplied snapshot to exercise nested keys and mixed JSON values.
    changes = app.state.repository.history(resource.id)
    change = changes[0]
    change.after[secret] = {"nested": [secret, 7, True, None, {"bearer": "Bearer fixture-token-123"}]}
    change.before["nested"] = [secret, False]
    change.evidence[0].quote = secret
    with app.state.repository._connect() as connection:
        connection.execute("UPDATE changes SET payload = ? WHERE id = ?", (change.model_dump_json(), change.id))
    with TestClient(app) as client:
        response = client.get(f"/api/resources/{resource.id}")
        assert response.status_code == 200
        assert secret not in response.text and "fixture-token-123" not in response.text
        body = response.json()
        nested = body["history"][0]["after"]["[密钥已隐藏]"]["nested"]
        assert nested[:4] == ["[密钥已隐藏]", 7, True, None]
        assert "[密钥已隐藏]" in nested[4]["bearer"]
        assert secret in app.state.repository.get_resource(resource.id).service
        task = client.get(f"/api/tasks/{run.id}").json()
        assert task["run"]["notes"] == ["[密钥已隐藏]"]
        assert task["run"]["error"] == "[密钥已隐藏]"
        assert body["history"][0]["before"]["nested"] == ["[密钥已隐藏]", False]
        assert body["history"][0]["evidence"][0]["quote"] == "[密钥已隐藏]"
        directory = settings.data_dir / "briefings"
        directory.mkdir(exist_ok=True)
        (directory / f"{run.id}.md").write_text(f"# Report\n\n{secret}\n", encoding="utf-8")
        report = client.get(f"/api/briefings/{run.id}").json()
        assert "[密钥已隐藏]" in Document(report["html"]).visible
        assert secret not in Document(report["html"]).visible
        assert client.get(f"/api/briefings/{run.id}/download").text == "# Report\n\n[密钥已隐藏]\n"
        assert report["run"]["has_briefing"] is True


def test_empty_api_collections_are_empty_without_starting_research(settings):
    researcher = Researcher()
    with TestClient(create_app(settings, researcher=researcher)) as client:
        for route in ("/api/resources", "/api/messages", "/api/tasks", "/api/briefings"):
            response = client.get(route)
            assert response.status_code == 200 and response.json() == []
        assert client.get("/api/app").json()["active_run"] is None
        assert researcher.calls == []


# Phase B: collection-first message feed, resource history and run messages.

LATER = CHECKED + timedelta(days=1)


def test_message_feed_lists_current_offers_filters_category_and_rejects_invalid_input(settings):
    app = create_app(settings, researcher=Researcher())
    repository = app.state.repository
    text = collected_message("Free Text API", "text")
    image = collected_message("Free Image API", "image")
    first, events = collect(repository, text, image)
    ids_by_category = {event.policy.category.value: event.resource_id for event in events}
    text_id = ids_by_category["text"]
    image_id = ids_by_category["image"]
    second, ended = collect(
        repository,
        collected_message(
            "Free Text API",
            "text",
            ended=True,
            end_reason="官方公告活动已停止",
        ),
        when=LATER,
    )
    assert {event.kind for event in ended} == {"expired"}
    assert first.id != second.id
    with TestClient(app) as client:
        feed = client.get("/api/messages")
        assert feed.status_code == 200
        body = feed.json()
        # The ended text offer is hidden by default; only the live image offer remains.
        assert [item["kind"] for item in body] == ["new"]
        assert [item["resource_id"] for item in body] == [image_id]
        # Explicit history shows the newest expired event ahead of the two earlier news.
        history = client.get("/api/messages?include_ended=true").json()
        assert history[0]["kind"] == "expired" and history[0]["resource_id"] == text_id
        assert {item["kind"] for item in history[1:]} == {"new"}
        # Category filter narrows to the matching family, including expired history.
        image_feed = client.get("/api/messages?category=image&include_ended=true").json()
        assert [item["kind"] for item in image_feed] == ["new"]
        assert [item["resource_id"] for item in image_feed] == [image_id]
        invalid = client.get("/api/messages?category=bogus")
        assert invalid.status_code == 422
        assert invalid.json() == {"detail": "研究范围或筛选条件无效，请检查输入后重试。"}

def test_resource_list_hides_all_ended_offers_but_history_and_expired_expose_them(settings):
    app = create_app(settings, researcher=Researcher())
    repository = app.state.repository
    _, events = collect(repository, collected_message("Free Text API", "text"))
    text_id = events[0].resource_id
    collect(repository, collected_message("Free Image API", "image"))
    _, live_events = collect(repository, collected_message("Free Video API", "video"))
    live = {event.resource_id for event in live_events}
    with TestClient(app) as client:
        default = client.get("/api/resources").json()
        assert text_id in {item["id"] for item in default}
        assert live <= {item["id"] for item in default}
        collect(
            repository,
            collected_message("Free Text API", "text", ended=True, end_reason="官方下线活动已结束"),
            when=LATER,
        )
        hidden = client.get("/api/resources").json()
        assert text_id not in {item["id"] for item in hidden}
        assert live <= {item["id"] for item in hidden}
        history = client.get("/api/resources?include_ended=true").json()
        assert text_id in {item["id"] for item in history}
        expired = client.get("/api/resources?status=expired").json()
        assert text_id in {item["id"] for item in expired}
        detail = client.get(f"/api/resources/{text_id}").json()
        assert [item["kind"] for item in detail["messages"]] == ["expired", "new"]


def test_task_detail_and_resource_detail_expose_that_runs_messages(settings):
    app = create_app(settings, researcher=Researcher())
    repository = app.state.repository
    first, _first_events = collect(repository, collected_message("Free Text API", "text"))
    second, second_events = collect(
        repository,
        collected_message("Free Text API", "text", ended=True, end_reason="官方公告活动结束"),
        when=LATER,
    )
    resource_id = second_events[0].resource_id
    with TestClient(app) as client:
        task1 = client.get(f"/api/tasks/{first.id}").json()
        task2 = client.get(f"/api/tasks/{second.id}").json()
        assert [item["kind"] for item in task1["messages"]] == ["new"]
        assert [item["kind"] for item in task2["messages"]] == ["expired"]
        detail = client.get(f"/api/resources/{resource_id}").json()
        assert [item["kind"] for item in detail["messages"]] == ["expired", "new"]
        assert detail["resource"]["id"] == resource_id


def test_legacy_strict_records_have_no_messages_on_detail_or_feed(settings):
    app = create_app(settings, researcher=Researcher())
    repository = app.state.repository
    run = seed(repository, policy("Verified Text API", "text"))
    resource_id = repository.list_resources()[0].id
    with TestClient(app) as client:
        assert client.get("/api/messages").json() == []
        assert client.get("/api/messages?include_ended=true").json() == []
        detail = client.get(f"/api/resources/{resource_id}").json()
        assert detail["messages"] == []
        task = client.get(f"/api/tasks/{run.id}").json()
        assert task["messages"] == []
        assert task["run"]["status"] == "success"


def test_message_feed_redacts_configured_secrets_from_collected_sources(settings):
    secret = "sk-live-1234567890"
    settings.model_api_key = secret
    app = create_app(settings, researcher=Researcher())
    repository = app.state.repository
    collect(
        repository,
        collected_message(
            "Free Text API",
            "text",
            excerpt=f"Free tier: use {secret} to authenticate API calls.",
            summary=f"Free tier requires none; sample key {secret} shown on the official page.",
        ),
    )
    with TestClient(app) as client:
        response = client.get("/api/messages")
        assert response.status_code == 200
        assert secret not in response.text
        assert "[密钥已隐藏]" in response.text


def test_app_labels_pending_and_active_and_feed_and_history_routes_in_openapi(settings):
    app = create_app(settings, researcher=Researcher())
    with TestClient(app) as client:
        labels = client.get("/api/app").json()["labels"]
        assert labels["pending"] == "未核验"
        assert labels["active"] == "政策已核验"
        schema = app.openapi()
        assert "/api/messages" in schema["paths"]
        resource_history = schema["paths"]["/api/resources"]["get"]["parameters"]
        assert any(
            param["name"] == "include_ended"
            and param["in"] == "query"
            and param["required"] is False
            for param in resource_history
        )
        assert "MessageSource" in schema["components"]["schemas"]
        assert "CollectedMessage" in schema["components"]["schemas"]
        assert "NewsItem" in schema["components"]["schemas"]


def test_export_openapi_has_no_configuration_or_data_side_effects(tmp_path):
    root = Path(__file__).resolve().parents[1]
    absent_config = tmp_path / "not-created" / "config.toml"
    absent_data = tmp_path / "not-created-data"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    env["AIFREERADAR_CONFIG"] = str(absent_config)
    env["AIFREERADAR_DATA_DIR"] = str(absent_data)
    result = subprocess.run(
        [sys.executable, "-m", "aifreeradar.export_openapi"],
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    schema = json.loads(result.stdout)
    assert "/api/tasks" in schema["paths"]
    assert "briefing_path" not in result.stdout
    assert not absent_config.parent.exists() and not absent_data.exists()
    assert list(tmp_path.iterdir()) == []
    request_schema = schema["components"]["schemas"]["CreateTaskRequest"]
    assert "categories" in request_schema["required"]
    download = schema["paths"]["/api/briefings/{task_id}/download"]["get"]["responses"]["200"]
    assert set(download["content"]) == {"text/markdown"}
    assert "Content-Disposition" in download["headers"]


# Phase C: same-origin SPA hosting, built assets, and deployment failure modes.

STATIC_APP = Path(__file__).resolve().parents[1] / "aifreeradar" / "static" / "app"
ENTRY = STATIC_APP / "index.html"
UNBUILT_MESSAGE = "前端尚未构建，请先运行 pnpm --dir frontend build。"
PAGE_ROUTES = ("/resources", "/resources/missing-resource", "/tasks", "/tasks/missing-task", "/briefings", "/briefings/missing-task")
CSP = (
    "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; "
    "style-src-attr 'unsafe-inline'; font-src 'self'; img-src 'none'; object-src 'none'; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)


def built_entry():
    if not ENTRY.is_file():
        pytest.skip("缺少前端构建产物 aifreeradar/static/app/index.html，先运行 pnpm --dir frontend build。")
    return ENTRY.read_bytes()


def test_root_serves_the_feed_spa_entry(settings):
    entry = built_entry()
    with TestClient(create_app(settings, researcher=Researcher())) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.content == entry
        assert response.headers["content-type"].split(";")[0].strip() == "text/html"


def test_six_spa_deep_links_serve_the_built_entry_even_for_missing_entities(settings):
    entry = built_entry()
    with TestClient(create_app(settings, researcher=Researcher())) as client:
        for path in PAGE_ROUTES:
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.content == entry, path
            assert response.headers["content-type"].split(";")[0].strip() == "text/html"
            assert response.headers["content-security-policy"] == CSP
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["referrer-policy"] == "same-origin"


def test_entry_scripts_and_styles_are_served_with_their_build_bytes_and_mime(settings):
    entry = built_entry()
    document = Document(entry.decode("utf-8"))
    references = [
        attrs["src"] for tag, attrs in document.elements
        if tag == "script" and attrs.get("src", "").startswith("/assets/")
    ]
    references += [
        attrs["href"] for tag, attrs in document.elements
        if tag == "link" and attrs.get("rel") == "stylesheet" and attrs.get("href", "").startswith("/assets/")
    ]
    assert any(reference.endswith(".js") for reference in references)
    assert any(reference.endswith(".css") for reference in references)
    with TestClient(create_app(settings, researcher=Researcher())) as client:
        for reference in references:
            assert ".." not in reference
            response = client.get(reference)
            assert response.status_code == 200, reference
            assert response.content == (STATIC_APP / reference.removeprefix("/")).read_bytes(), reference
            media_type = response.headers["content-type"].split(";")[0].strip().lower()
            if reference.endswith(".css"):
                assert media_type == "text/css", reference
            else:
                assert media_type in {"text/javascript", "application/javascript", "application/x-javascript"}, reference


def test_missing_assets_and_unknown_api_routes_are_real_404s_not_the_entry(settings):
    with TestClient(create_app(settings, researcher=Researcher())) as client:
        asset = client.get("/assets/no-such-asset.js")
        assert asset.status_code == 404
        assert not asset.headers.get("content-type", "").startswith("text/html")
        api = client.get("/api/no-such-route")
        assert api.status_code == 404
        assert api.headers["content-type"].startswith("application/json")
        assert api.json() == {"detail": "未找到此接口。"}
        if ENTRY.is_file():
            entry = ENTRY.read_bytes()
            assert asset.content != entry
            assert api.content != entry


def test_unknown_browser_route_returns_the_entry_with_http_404(settings):
    entry = built_entry()
    with TestClient(create_app(settings, researcher=Researcher())) as client:
        response = client.get("/no-such-page")
        assert response.status_code == 404
        assert response.content == entry
        assert response.headers["content-type"].split(";")[0].strip() == "text/html"


def test_missing_build_page_response_keeps_api_and_health_working(tmp_path):
    repository_root = Path(__file__).resolve().parents[1]
    package_root = tmp_path / "isolated"
    shutil.copytree(
        repository_root / "aifreeradar",
        package_root / "aifreeradar",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "static", "templates"),
    )
    probe = tmp_path / "probe.py"
    probe.write_text(
        f"""import json
import tempfile
from pathlib import Path

import aifreeradar
from fastapi.testclient import TestClient

from aifreeradar.config import Settings
from aifreeradar.web import create_app


class IdleResearcher:
    async def research(self, scope, existing):
        raise AssertionError("研究不应启动")


pages = {{}}
with tempfile.TemporaryDirectory() as data:
    app = create_app(Settings(data_dir=Path(data), schedule_enabled=False), researcher=IdleResearcher())
    with TestClient(app) as client:
        for path in {PAGE_ROUTES!r}:
            response = client.get(path)
            pages[path] = [response.status_code, response.text, response.headers.get("content-type", "")]
        api = client.get("/api/resources")
        health = client.get("/health")
        asset = client.get("/assets/no-such-asset.js")
        payload = {{
            "package": str(Path(aifreeradar.__file__).resolve()),
            "pages": pages,
            "api": [api.status_code, api.headers.get("content-type", "")],
            "health": [health.status_code, health.json()],
            "asset": [asset.status_code, asset.headers.get("content-type", "")],
        }}
print(json.dumps(payload, ensure_ascii=True))
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(package_root)
    result = subprocess.run(
        [sys.executable, str(probe)],
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert Path(payload["package"]).is_relative_to(package_root)
    for path, (status, text, content_type) in payload["pages"].items():
        assert status == 503, path
        assert text == UNBUILT_MESSAGE, path
        assert content_type.startswith("text/plain"), path
    assert payload["api"][0] == 200
    assert payload["api"][1].startswith("application/json")
    health_status, health_body = payload["health"]
    assert health_status == 200
    assert health_body["status"] == "ok"
    assert set(health_body) == {"status", "version"}
    assert isinstance(health_body["version"], str) and health_body["version"]
    assert payload["asset"][0] == 404
    assert not payload["asset"][1].startswith("text/html")


def test_responses_use_the_final_content_security_policy(settings):
    with TestClient(create_app(settings, researcher=Researcher())) as client:
        for path in ("/health", "/api/resources"):
            response = client.get(path)
            assert response.headers["content-security-policy"] == CSP
        if ENTRY.is_file():
            assert client.get("/resources").headers["content-security-policy"] == CSP


def test_legacy_download_alias_is_removed_while_the_api_download_works(settings):
    app = create_app(settings, researcher=Researcher())
    with TestClient(app) as client:
        task_id = post_run(client)
        wait_idle(client, app)
        download = client.get(f"/api/briefings/{task_id}/download")
        assert download.status_code == 200
        assert task_id in download.text
        assert download.headers["content-type"].startswith("text/markdown")
        legacy = client.get(f"/briefings/{task_id}/download", follow_redirects=False)
        assert legacy.status_code != 200
        assert not legacy.headers.get("content-type", "").startswith("text/markdown")
        assert legacy.content != download.content
        if ENTRY.is_file():
            assert legacy.status_code == 404


# Phase D: human review workbench for pending leads.

REVIEW_STATES = {"open": "未处理", "confirmed": "已确认", "rejected": "已驳回", "ignored": "已忽略"}


def test_leads_filter_sort_default_review_and_open_leads_count(settings):
    app = create_app(settings, researcher=Researcher())
    repository = app.state.repository
    seed(repository, policy("Stable API"), when=CHECKED)
    seed(repository, policy("Flaky API"), when=CHECKED)
    seed(
        repository,
        policy("Pending Older", status="pending", evidence=[]),
        when=CHECKED + timedelta(hours=1),
    )
    seed(
        repository,
        policy("Flaky API", check_status="failed", failure_reason="source unreachable"),
        when=CHECKED + timedelta(hours=2),
    )
    seed(
        repository,
        policy("Pending Newer", status="pending", evidence=[]),
        when=CHECKED + timedelta(hours=3),
    )
    seed(
        repository,
        policy("Collected Pending API", status="pending", evidence=[]),
        when=CHECKED + timedelta(hours=1),
    )
    collect(
        repository,
        collected_message("Flaky API"),
        collected_message("Collected Pending API"),
    )
    expected = ["Pending Newer", "Pending Older"]
    with TestClient(app) as client:
        leads = client.get("/api/leads")
        assert leads.status_code == 200
        assert [item["resource"]["service"] for item in leads.json()] == expected
        for item in leads.json():
            review = item["review"]
            assert review["resource_id"] == item["resource"]["id"]
            assert review["state"] == "open"
            assert review["favorite"] is False and review["note"] == ""
        assert client.get("/api/resources").json()[0]["service"] == "Stable API"
        app_data = client.get("/api/app").json()
        assert app_data["review_states"] == REVIEW_STATES
        assert app_data["open_leads"] == len(expected)
        assert client.get("/api/reviews").json() == []

        lead_id = leads.json()[0]["resource"]["id"]
        ignored = client.post(f"/api/resources/{lead_id}/review", json={"action": "ignore"})
        assert ignored.status_code == 200
        remaining = client.get("/api/leads").json()
        assert [item["resource"]["service"] for item in remaining] == expected[1:]
        assert client.get("/api/app").json()["open_leads"] == len(expected) - 1
        reviews = client.get("/api/reviews").json()
        assert [(review["resource_id"], review["state"]) for review in reviews] == [
            (lead_id, "ignored")
        ]


def test_resource_review_round_trip_audit_and_idempotency(settings):
    app = create_app(settings, researcher=Researcher())
    seed(app.state.repository, policy())
    resource_id = app.state.repository.list_resources()[0].id
    url = f"/api/resources/{resource_id}/review"
    with TestClient(app) as client:
        detail = client.get(f"/api/resources/{resource_id}").json()
        assert detail["review"]["state"] == "open"
        assert detail["review"]["favorite"] is False and detail["review"]["note"] == ""
        assert detail["actions"] == []

        confirmed = client.post(url, json={"action": "confirm"})
        assert confirmed.status_code == 200
        body = confirmed.json()
        assert body["review"]["state"] == "confirmed"
        assert len(body["actions"]) == 1
        action = body["actions"][0]
        assert action["action"] == "confirm" and action["resource_id"] == resource_id
        assert action["before"]["state"] == "open" and action["after"]["state"] == "confirmed"
        assert action["after"]["favorite"] is False
        assert client.get("/api/resources").json()[0]["status"] == "active"

        repeated = client.post(url, json={"action": "confirm"})
        assert repeated.status_code == 200
        assert len(repeated.json()["actions"]) == 1
        assert repeated.json()["review"] == body["review"]

        favorited = client.post(url, json={"action": "favorite"}).json()
        assert favorited["review"]["favorite"] is True
        assert favorited["actions"][-1]["action"] == "favorite"
        assert len(favorited["actions"]) == 2

        noted = client.post(url, json={"action": "note", "note": "  需要人工复核  "}).json()
        assert noted["review"]["note"] == "需要人工复核"
        assert noted["actions"][-1]["action"] == "note"

        rejected = client.post(url, json={"action": "reject"}).json()
        assert rejected["review"]["state"] == "rejected"
        assert rejected["review"]["favorite"] is True
        reopened = client.post(url, json={"action": "reopen"}).json()
        assert reopened["review"]["state"] == "open"
        unfavorited = client.post(url, json={"action": "unfavorite"}).json()
        assert unfavorited["review"]["favorite"] is False
        ignored = client.post(url, json={"action": "ignore"}).json()
        assert ignored["review"]["state"] == "ignored"
        assert len(ignored["actions"]) == 7

        detail = client.get(f"/api/resources/{resource_id}").json()
        assert detail["review"]["state"] == "ignored"
        assert detail["review"]["note"] == "需要人工复核"
        assert detail["resource"]["status"] == "active"
        assert client.get("/api/resources").json()[0]["status"] == "active"


def test_review_validation_missing_resources_and_ignored_recheck(settings):
    researcher = Researcher()
    app = create_app(settings, researcher=researcher)
    seed(app.state.repository, policy())
    resource_id = app.state.repository.list_resources()[0].id
    missing = {"detail": "未找到此资源。请返回资源库选择已有资源。"}
    with TestClient(app) as client:
        overlong = client.post(
            f"/api/resources/{resource_id}/review", json={"action": "note", "note": "x" * 2001}
        )
        assert overlong.status_code == 422
        assert overlong.json() == {"detail": "研究范围或筛选条件无效，请检查输入后重试。"}
        assert client.get(f"/api/resources/{resource_id}").json()["review"]["note"] == ""

        unknown = client.post("/api/resources/missing/review", json={"action": "confirm"})
        assert unknown.status_code == 404 and unknown.json() == missing
        missing_recheck = client.post("/api/resources/missing/recheck")
        assert missing_recheck.status_code == 404 and missing_recheck.json() == missing

        ignored = client.post(f"/api/resources/{resource_id}/review", json={"action": "ignore"})
        assert ignored.status_code == 200
        blocked = client.post(f"/api/resources/{resource_id}/recheck")
        assert blocked.status_code == 409
        assert blocked.json() == {"detail": "该资源已标记忽略，请先恢复处理后再重查。"}
        assert app.state.repository.review(resource_id).state == "ignored"
        assert len(app.state.repository.list_runs()) == 1 and researcher.calls == []


@pytest.mark.parametrize("suffix,payload", [("review", {"action": "confirm"}), ("recheck", None)])
def test_foreign_origin_cannot_review_or_recheck(settings, suffix, payload):
    researcher = Researcher()
    app = create_app(settings, researcher=researcher)
    seed(app.state.repository, policy())
    resource_id = app.state.repository.list_resources()[0].id
    with TestClient(app) as client:
        for headers in ({"origin": "https://evil.example"}, {"sec-fetch-site": "cross-site"}):
            response = client.post(
                f"/api/resources/{resource_id}/{suffix}", json=payload, headers=headers
            )
            assert response.status_code == 403
        assert app.state.repository.review(resource_id).state == "open"
        assert app.state.repository.actions(resource_id) == []
        assert len(app.state.repository.list_runs()) == 1 and researcher.calls == []


def test_recheck_starts_single_resource_run_and_appears_in_openapi(settings):
    researcher = Researcher()
    app = create_app(settings, researcher=researcher)
    seed(app.state.repository, policy())
    resource = app.state.repository.list_resources()[0]
    researcher.results = [ResearchBatch(resources=[policy(resource_id=resource.id)])]
    with TestClient(app) as client:
        response = client.post(f"/api/resources/{resource.id}/recheck")
        assert response.status_code == 202
        body = response.json()
        assert body["trigger"] == "manual"
        assert body["scope"]["resource_ids"] == [resource.id]
        assert body["scope"]["categories"] == [resource.category]
        assert "briefing_path" not in body
        assert body["id"] in [run["id"] for run in client.get("/api/tasks").json()]
        assert app.state.repository.actions(resource.id) == []
        wait_idle(client, app)
        assert app.state.repository.get_run(body["id"]).status == "success"
        assert len(researcher.calls) == 1
        assert researcher.calls[0][0].resource_ids == [resource.id]
        schema = app.openapi()
        for path in (
            "/api/leads",
            "/api/reviews",
            "/api/resources/{resource_id}/review",
            "/api/resources/{resource_id}/recheck",
        ):
            assert path in schema["paths"]


def test_manual_task_preserves_explicit_resource_verification_scope(settings):
    researcher = Researcher()
    app = create_app(settings, researcher=researcher)
    seed(app.state.repository, policy())
    resource = app.state.repository.list_resources()[0]
    with TestClient(app) as client:
        response = client.post(
            "/api/tasks",
            json={"categories": ["text"], "region": "china", "resource_ids": [resource.id]},
        )
        assert response.status_code == 202
        assert response.json()["scope"]["resource_ids"] == [resource.id]
        wait_idle(client, app)
        assert researcher.calls[0][0].resource_ids == [resource.id]


def test_detail_models_accept_backward_payloads_without_message_fields(settings):
    app = create_app(settings, researcher=Researcher())
    run = seed(app.state.repository, policy())
    resource = app.state.repository.list_resources()[0]
    with TestClient(app) as client:
        task_payload = client.get(f"/api/tasks/{run.id}").json()
        task_payload.pop("messages")
        assert TaskDetailRead.model_validate(task_payload).messages == []
        resource_payload = client.get(f"/api/resources/{resource.id}").json()
        resource_payload.pop("messages")
        resource_payload["resource"].pop("messages", None)
        detail = ResourceDetailRead.model_validate(resource_payload)
        assert detail.messages == []
        assert detail.resource.messages == []


# --- Additive zh translation through the HTTP surface ---

class FixedTranslator:
    """Deterministic stand-in for ModelTranslator in HTTP tests."""

    def __init__(self) -> None:
        self.batches: list[dict[str, str]] = []

    async def translate(self, texts: dict[str, str]) -> dict[str, str]:
        self.batches.append(dict(texts))
        return {key: f"中文译文：{value}" for key, value in texts.items()}


def install_translator(monkeypatch, translator):
    monkeypatch.setattr("aifreeradar.translation.ModelTranslator", lambda settings: translator)


def test_same_origin_translation_backfill_returns_202_and_persists_zh(settings, monkeypatch):
    translator = FixedTranslator()
    install_translator(monkeypatch, translator)
    app = create_app(settings, researcher=Researcher())
    repository = app.state.repository
    seed(
        repository,
        policy(
            "Pending Lead",
            status="pending",
            quota=UNKNOWN,
            failure_reason="Official documentation does not state the free quota",
        ),
    )
    message = collected_message("Free Text API", "text").model_copy(
        update={"title": "Free Text API free tier announced"}
    )
    collect(repository, message)
    stored_lead = next(item for item in repository.list_resources() if item.service == "Pending Lead")

    with TestClient(app) as client:
        response = client.post("/api/translations/backfill", headers={"origin": "http://testserver"})
        assert response.status_code == 202, response.text
        body = response.json()
        assert set(body) == {
            "id",
            "trigger",
            "scope",
            "status",
            "started_at",
            "finished_at",
            "error",
            "notes",
            "schedule_day",
            "stats",
            "has_briefing",
        }
        assert body["trigger"] == "manual"
        assert body["status"] == "running"
        wait_idle(client, app)

        saved = client.get(f"/api/tasks/{body['id']}").json()["run"]
        assert saved["status"] == "success"
        assert any("译文回填完成" in note for note in saved["notes"])

        (item,) = client.get("/api/messages").json()
        assert item["title_zh"] == "中文译文：Free Text API free tier announced"
        assert item["summary_zh"] == (
            "中文译文：Free API tier with 1000 monthly requests and no purchase required."
        )
        assert item["title"] == "Free Text API free tier announced"
        assert item["summary"] == "Free API tier with 1000 monthly requests and no purchase required."

        lead = next(
            entry
            for entry in client.get("/api/leads").json()
            if entry["resource"]["service"] == "Pending Lead"
        )
        assert lead["resource"]["failure_reason"] == stored_lead.failure_reason
        assert lead["resource"]["failure_reason_zh"] == f"中文译文：{stored_lead.failure_reason}"
    assert translator.batches


@pytest.mark.parametrize(
    "headers, expected",
    [
        ({"host": "evil.example"}, {400, 403}),
        ({"host": "127.0.0.1.evil.example"}, {400, 403}),
        ({"origin": "https://evil.example"}, {403}),
        ({"origin": "null"}, {403}),
        ({"origin": "http://testserver:18765"}, {403}),
        ({"sec-fetch-site": "cross-site"}, {403}),
    ],
)
@pytest.mark.parametrize("path", ["/api/translations/backfill", "/api/messages/backfill"])
def test_foreign_host_or_origin_cannot_backfill_translations(
    settings, monkeypatch, headers, expected, path
):
    translator = FixedTranslator()
    install_translator(monkeypatch, translator)
    app = create_app(settings, researcher=Researcher())
    with TestClient(app) as client:
        response = client.post(path, headers=headers)
        assert response.status_code in expected
        assert app.state.repository.list_runs() == []
        assert translator.batches == []


@pytest.mark.parametrize("path", ["/api/translations/backfill", "/api/messages/backfill"])
def test_busy_task_returns_conflict_for_translation_backfill(settings, monkeypatch, path):
    translator = FixedTranslator()
    install_translator(monkeypatch, translator)
    researcher = Researcher(blocked=True)
    app = create_app(settings, researcher=researcher)
    with TestClient(app) as client:
        post_run(client)
        try:
            assert researcher.entered.wait(timeout=3)
            response = client.post(path)
            assert response.status_code == 409
            assert response.json() == {
                "detail": "已有研究任务运行中，当前无法发起另一项任务。查看运行中的任务，完成后再试。"
            }
            assert len(app.state.repository.list_runs()) == 1
            assert translator.batches == []
        finally:
            assert client.portal is not None
            client.portal.call(researcher.release.set)
            wait_idle(client, app)


def test_leads_messages_resources_and_task_detail_expose_zh_alongside_originals(settings):
    app = create_app(settings, researcher=Researcher())
    repository = app.state.repository
    seed(
        repository,
        policy(
            "Pending Lead",
            status="pending",
            evidence=[],
            failure_reason="Official documentation does not state the free quota",
        ),
    )
    message = collected_message("Free Text API", "text").model_copy(
        update={"title": "Free Text API free tier announced"}
    )
    run, events = collect(repository, message)
    (event,) = events
    lead = next(item for item in repository.list_resources() if item.service == "Pending Lead")
    repository.save_resource_translations(
        [lead.model_copy(update={"failure_reason_zh": "官方文档未说明免费额度"})]
    )
    repository.save_news_translations(
        [
            event.model_copy(
                update={
                    "title_zh": "免费文本接口层级发布",
                    "summary_zh": "免费接口层级，每月一千次请求，无需购买",
                    "policy": event.policy.model_copy(update={"quota_zh": "每月一千次请求"}),
                }
            )
        ]
    )
    resource = repository.get_resource(event.resource_id)
    assert resource is not None
    repository.save_message_translations(
        resource.id,
        [
            offer.model_copy(
                update={
                    "title_zh": "免费文本接口层级发布",
                    "summary_zh": "免费接口层级，每月一千次请求，无需购买",
                }
            )
            for offer in resource.messages
        ],
    )

    with TestClient(app) as client:
        leads = client.get("/api/leads").json()
        lead_item = next(
            entry for entry in leads if entry["resource"]["service"] == "Pending Lead"
        )
        assert lead_item["resource"]["failure_reason_zh"] == "官方文档未说明免费额度"
        assert lead_item["resource"]["failure_reason"] == lead.failure_reason
        assert lead_item["resource"]["quota_zh"] == ""

        feed = client.get("/api/messages").json()
        message_item = next(entry for entry in feed if entry["id"] == event.id)
        assert message_item["title_zh"] == "免费文本接口层级发布"
        assert message_item["summary_zh"] == "免费接口层级，每月一千次请求，无需购买"
        assert message_item["title"] == event.title
        assert message_item["summary"] == event.summary
        assert message_item["policy"]["quota_zh"] == "每月一千次请求"
        assert message_item["policy"]["quota"] == event.policy.quota
        assert message_item["sources"][0]["excerpt"] == event.sources[0].excerpt
        assert message_item["policy"]["claim_conditions_zh"] == ""
        assert message_item["end_reason_zh"] == ""

        resources = client.get("/api/resources").json()
        listed = next(item for item in resources if item["id"] == event.resource_id)
        assert listed["messages"][0]["title_zh"] == "免费文本接口层级发布"
        assert listed["messages"][0]["title"] == event.title

        detail = client.get(f"/api/resources/{event.resource_id}").json()
        assert detail["resource"]["messages"][0]["summary_zh"] == "免费接口层级，每月一千次请求，无需购买"
        assert detail["resource"]["quota"] == event.policy.quota

        task = client.get(f"/api/tasks/{run.id}").json()
        assert task["messages"][0]["title_zh"] == "免费文本接口层级发布"
        assert task["messages"][0]["title"] == event.title


def test_source_backfill_api_collects_pending_history_without_verifying_or_refreshing_age(settings, monkeypatch):
    install_translator(monkeypatch, FixedTranslator())

    class SourceResearcher(Researcher):
        async def collect_sources(self, resources):
            self.calls.append(resources)
            message = collected_message(
                resources[0].service, excerpt="Free API tier: 1000 requests per month."
            )
            message.policy.resource_id = resources[0].id
            return ResearchBatch(messages=[message])

    researcher = SourceResearcher()
    app = create_app(settings, researcher=researcher)
    repository = app.state.repository
    seed(repository, policy("Missing History", status="pending", evidence=[]))
    (original,) = repository.list_resources()
    with TestClient(app) as client:
        assert client.get("/api/app").json()["open_leads"] == 1
        response = client.post("/api/messages/backfill", headers={"origin": "http://testserver"})
        assert response.status_code == 202
        run_id = response.json()["id"]
        assert response.json()["scope"]["resource_ids"] == []
        wait_idle(client, app)
        saved = client.get(f"/api/tasks/{run_id}").json()["run"]
        assert saved["status"] == "success" and not saved["error"]
        assert client.get("/api/leads").json() == []
        assert client.get("/api/app").json()["open_leads"] == 0
        (resource,) = client.get("/api/resources").json()
        assert resource["status"] == "pending" and resource["messages"][0]["sources"]
        assert datetime.fromisoformat(resource["first_seen_at"]) == original.first_seen_at
        (event,) = client.get("/api/messages").json()
        assert datetime.fromisoformat(event["discovered_at"]) == original.first_seen_at
        if original.last_success_at is None:
            assert resource["last_success_at"] is None
        else:
            assert datetime.fromisoformat(resource["last_success_at"]) == original.last_success_at
        again = client.post("/api/messages/backfill")
        assert again.status_code == 202
        wait_idle(client, app)
        assert len(researcher.calls) == 1
        assert len(client.get("/api/messages").json()) == 1
