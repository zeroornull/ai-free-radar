"""Collection-first message lifecycle: no auto missing failures, source safety, briefings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from domain_fixtures import official_policy

from aifreeradar.briefing import markdown_link, render_briefing
from aifreeradar.config import Settings
from aifreeradar.models import (
    Category,
    CollectedMessage,
    MessageSource,
    NewsItem,
    Policy,
    ResearchBatch,
    Run,
    Scope,
)
from aifreeradar.service import TaskManager
from aifreeradar.storage import Repository

BASE_TIME = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
CHECKED = datetime(2026, 11, 1, 1, tzinfo=UTC)


def message_policy(**updates):
    values = {
        "provider": "Example Provider",
        "service": "Example API",
        "category": Category.TEXT,
        "provider_domain": "example.com",
        "service_key": "example-api",
        "api_url": "https://example.com/api",
        "docs_url": "https://example.com/docs",
        "free_type": "limited",
        "quota": "100",
        "quota_unit": "requests",
        "refresh_cycle": "monthly",
        "rate_limit": "未说明",
        "claim_conditions": "须注册；可能要求绑定支付方式",
        "payment_required": False,
        "payment_method_required": True,
        "expires_at": None,
        "expiry_notes": "未说明",
        "region_restrictions": "未说明",
        "china_policy": "unknown",
        "status": "pending",
    }
    values.update(updates)
    return Policy(**values)


def source(**updates):
    values = {
        "url": "https://example.com/free-tier",
        "title": "Free tier",
        "excerpt": "Example API gives every new account 100 free requests per month.",
        "source_type": "official",
        "access": "page",
        "published_at": BASE_TIME - timedelta(days=1),
    }
    values.update(updates)
    return MessageSource(**values)


def message(**updates):
    values = {
        "policy": message_policy(),
        "offer_key": "default",
        "title": "Example API free tier",
        "summary": "100 free requests per month for new accounts.",
        "sources": [source()],
        "published_at": None,
    }
    values.update(updates)
    return CollectedMessage(**values)


def news_item(task_id="news", resource_id="r1", kind="new", **updates):
    base = message().model_dump()
    base.update(
        id="m1",
        resource_id=resource_id,
        task_id=task_id,
        kind=kind,
        discovered_at=BASE_TIME,
        first_seen_at=BASE_TIME,
    )
    base.update(updates)
    return NewsItem(**base)


def completed_run(task_id: str = "news") -> Run:
    return Run(
        id=task_id,
        scope=Scope(),
        trigger="manual",
        status="success",
        started_at=BASE_TIME,
        finished_at=BASE_TIME,
    )


def verified_policy(**updates):
    values = {
        "provider": "Example Provider",
        "service": "Example API",
        "provider_domain": "example.com",
        "service_key": "example-api",
    }
    values.update(updates)
    return official_policy(checked_at=CHECKED, **values)


class MessageResearcher:
    def __init__(self, *batches):
        self.batches = list(batches) or [ResearchBatch()]
        self.calls = []

    async def research(self, scope, existing):
        self.calls.append((scope.model_copy(deep=True), list(existing)))
        result = self.batches.pop(0) if len(self.batches) > 1 else self.batches[0]
        return result.model_copy(deep=True)


def seed_verified(repository):
    run = Run(scope=Scope(), started_at=CHECKED, status="success", finished_at=CHECKED)
    repository.save_run(run)
    policy = verified_policy()
    repository.apply_batch(ResearchBatch(resources=[policy]), run, CHECKED)
    return repository.list_resources()[0]


def test_message_briefing_renders_incremental_source_backed_news():
    markdown = render_briefing(
        completed_run(),
        [],
        [],
        [],
        messages=[
            news_item(
                sources=[
                    source(),
                    source(
                        url="https://forum.example.net/thread/1",
                        source_type="community",
                        access="snippet",
                        published_at=None,
                        excerpt="Community post: the free API tier includes 100 requests.",
                    ),
                ]
            ),
            news_item(
                id="m2",
                kind="expired",
                ended=True,
                end_reason="官网公告停止免费额度",
            ),
        ],
    )
    assert "## 消息动态" in markdown
    assert "本次来源记录 2 条" in markdown
    assert "Example API free tier" in markdown
    assert "新发现" in markdown and "已结束" in markdown
    assert "结束依据：官网公告停止免费额度" in markdown
    # Source type, access, traceable URL, publication vs discovery time.
    assert "官方页面（网页原文）" in markdown
    assert "<https://example.com/free-tier>" in markdown
    assert "社区（搜索摘要）" in markdown
    assert "发布时间未说明" in markdown
    assert "中国大陆政策：未说明" in markdown
    assert "来源发布时间：来源未注明发布时间" in markdown
    assert "2026\\-11\\-09" in markdown
    assert "发现时间：2026\\-11\\-10" in markdown
    # Unknown terms stay unknown; card binding is reported, not judged paid.
    assert "需要绑定支付方式" in markdown
    assert "未经官方政策逐项核验" in markdown
    # No repeated pending recap on a collection briefing.
    assert "待核实线索" not in markdown


def test_message_briefing_escapes_untrusted_text_and_links():
    markdown = render_briefing(
        completed_run(),
        [],
        [],
        [],
        messages=[
            news_item(
                title="[evil](https://evil.example) *bold*",
                summary="see **claim** `code`",
                sources=[
                    source(
                        excerpt="quote with | pipe and # hash",
                        title="",
                    )
                ],
            )
        ],
    )
    assert "\\[evil\\]\\(https://evil\\.example\\) \\*bold\\*" in markdown
    assert "see \\*\\*claim\\*\\* \\`code\\`" in markdown
    assert "quote with \\| pipe and \\# hash" in markdown
    unsafe = markdown_link("label", "javascript:alert(1)")
    assert unsafe == "label：javascript:alert\\(1\\)"
    assert "<javascript:" not in unsafe


def test_incremental_message_kinds_report_unchanged_run_without_news_line():
    markdown = render_briefing(completed_run(), [], [], [], messages=[])
    assert "本次无新增或变化" in markdown


@pytest.mark.asyncio
async def test_collection_run_persists_messages_without_marking_history_missing(tmp_path):
    settings = Settings(data_dir=tmp_path, schedule_enabled=False)
    repository = Repository(tmp_path)
    original = seed_verified(repository)
    collected = message()
    # Reported offer claims the same service as the verified record; collection
    # must not overwrite verified facts, must not require a recheck result.
    researcher = MessageResearcher(ResearchBatch(messages=[collected]))
    manager = TaskManager(settings, repository, researcher)
    run = await manager.start(Scope(categories=[Category.TEXT]))
    await manager.wait_idle()
    await manager.close()

    saved = repository.get_run(run.id)
    assert saved is not None and saved.briefing_path is not None
    assert saved.status == "success"
    # The verified resource is untouched by collection, including no missing recheck.
    current = repository.get_resource(original.id)
    assert current is not None
    assert current.quota == original.quota and current.status == original.status
    assert current.check_status == original.check_status
    assert current.last_success_at == original.last_success_at

    records = repository.list_messages()
    assert len(records) == 1
    assert records[0].task_id == run.id and records[0].kind == "new"
    assert records[0].title == collected.title
    briefing = Path(saved.briefing_path).read_text(encoding="utf-8")
    assert collected.title in briefing
    assert "待核实线索" not in briefing


@pytest.mark.asyncio
async def test_collection_failure_is_partial_without_incomplete_resources(tmp_path):
    settings = Settings(data_dir=tmp_path, schedule_enabled=False)
    repository = Repository(tmp_path)
    original = seed_verified(repository)
    researcher = MessageResearcher(
        ResearchBatch(messages=[message()], failures=["搜索源超时"])
    )
    manager = TaskManager(settings, repository, researcher)
    run = await manager.start(Scope(categories=[Category.TEXT]))
    await manager.wait_idle()
    await manager.close()

    saved = repository.get_run(run.id)
    assert saved is not None and saved.status == "partial"
    assert "搜索源超时" in saved.error
    current = repository.get_resource(original.id)
    assert current is not None
    assert current.quota == original.quota
    assert current.evidence == original.evidence
    assert current.check_status == original.check_status
    assert current.last_success_at == original.last_success_at
    assert saved.briefing_path is not None
    briefing = Path(saved.briefing_path).read_text(encoding="utf-8")
    assert "搜索源超时" in briefing


@pytest.mark.asyncio
async def test_explicit_verification_preserves_failed_policy(tmp_path):
    settings = Settings(data_dir=tmp_path, schedule_enabled=False)
    repository = Repository(tmp_path)
    original = seed_verified(repository)
    failed = verified_policy(
        service_key=original.service_key,
        resource_id=original.id,
        check_status="failed",
        failure_reason="官方政策页无法访问",
        payment_method_required=True,
    )
    researcher = MessageResearcher(ResearchBatch(resources=[failed]))
    manager = TaskManager(settings, repository, researcher)
    run = await manager.start(
        Scope(categories=[Category.TEXT], resource_ids=[original.id])
    )
    await manager.wait_idle()
    await manager.close()

    saved = repository.get_run(run.id)
    assert saved is not None and saved.status == "partial"
    current = repository.get_resource(original.id)
    assert current is not None
    # Prior verified facts survive a failed strict recheck.
    assert current.quota == original.quota
    assert current.payment_required is False
    assert current.last_success_at == original.last_success_at
    assert current.check_status == "failed"
    assert saved.briefing_path is not None
    briefing = Path(saved.briefing_path).read_text(encoding="utf-8")
    assert failed.failure_reason in briefing
    # Verification output is not turned into collection news.
    assert "消息动态" not in briefing


@pytest.mark.asyncio
async def test_ignored_resource_messages_are_kept_out_of_collection(tmp_path):
    settings = Settings(data_dir=tmp_path, schedule_enabled=False)
    repository = Repository(tmp_path)
    original = seed_verified(repository)
    repository.apply_review(original.id, "ignore")
    researcher = MessageResearcher(
        ResearchBatch(messages=[message(policy=message_policy(resource_id=original.id))])
    )
    manager = TaskManager(settings, repository, researcher)
    run = await manager.start(Scope(categories=[Category.TEXT]))
    await manager.wait_idle()
    await manager.close()

    saved = repository.get_run(run.id)
    assert saved is not None and saved.status == "success"
    assert repository.list_messages() == []
    assert saved.briefing_path is not None
    briefing = Path(saved.briefing_path).read_text(encoding="utf-8")
    assert "Example API free tier" not in briefing


@pytest.mark.asyncio
async def test_collected_snippets_are_redacted_in_report(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_REPORT_SECRET", "supersecret-token-42")
    settings = Settings(data_dir=tmp_path, schedule_enabled=False)
    repository = Repository(tmp_path)
    researcher = MessageResearcher(
        ResearchBatch(
            messages=[
                message(
                    summary="100 free API requests; reference supersecret-token-42",
                    sources=[
                        source(
                            excerpt="100 free API requests. Bearer supersecret-token-42 granted"
                        )
                    ],
                )
            ]
        )
    )
    manager = TaskManager(settings, repository, researcher)
    run = await manager.start(Scope(categories=[Category.TEXT]))
    await manager.wait_idle()
    await manager.close()

    saved = repository.get_run(run.id)
    assert saved is not None and saved.briefing_path is not None
    briefing = Path(saved.briefing_path).read_text(encoding="utf-8")
    assert "supersecret-token-42" not in briefing
    assert "已隐藏凭据" in briefing
    records = repository.list_messages()
    assert records and "supersecret-token-42" not in records[0].summary


@pytest.mark.asyncio
async def test_collection_scope_excludes_out_of_scope_messages(tmp_path):
    settings = Settings(data_dir=tmp_path, schedule_enabled=False)
    repository = Repository(tmp_path)
    researcher = MessageResearcher(
        ResearchBatch(
            messages=[message(policy=message_policy(category=Category.IMAGE))]
        )
    )
    manager = TaskManager(settings, repository, researcher)
    run = await manager.start(Scope(categories=[Category.TEXT]))
    await manager.wait_idle()
    await manager.close()

    saved = repository.get_run(run.id)
    assert saved is not None and saved.status == "success"
    assert repository.list_messages() == []
    assert saved.briefing_path is not None
    briefing = Path(saved.briefing_path).read_text(encoding="utf-8")
    assert "Example API free tier" not in briefing