"""Domain regression tests for managed sources, optional facts, and traces."""

from __future__ import annotations

import re
import sqlite3
from datetime import timedelta

import pytest
from domain_fixtures import BASE_TIME, completed_run, official_policy, revise_policy

from aifreeradar.briefing import render_briefing
from aifreeradar.models import (
    Category,
    CollectedMessage,
    MessageSource,
    ModelDeployment,
    Policy,
    QuotaFact,
    ResearchBatch,
    ResearchTrace,
    RuleMatch,
    SourceDefinition,
    SourceEntry,
    SourceSnapshot,
    SourceState,
)
from aifreeradar.storage import MIGRATIONS, Repository, message_problem

SOURCE_URL = "https://news.example.com/free-api"
FEED_URL = "https://news.example.com/feed.xml"
QUOTA_QUOTE = (
    "Free tier: 1000 requests per month for text-model; image tier: 200 images."
)


def visible(markdown: str) -> str:
    return re.sub(r"\\([^\w\s])", r"\1", markdown)


@pytest.fixture
def repository(tmp_path):
    return Repository(tmp_path / "data")


def quota(**overrides) -> QuotaFact:
    values = {
        "amount": 1000,
        "unit": "requests",
        "period": "month",
        "scope": "text",
        "condition": "Free tier",
        "model_ids": ["text-model"],
        "source_url": SOURCE_URL,
        "quote": QUOTA_QUOTE,
        "value_phrase": "1000 requests",
    }
    values.update(overrides)
    return QuotaFact(**values)


def deployment(**overrides) -> ModelDeployment:
    values = {
        "provider": "Example",
        "model_id": "text-model",
        "base_model": "text-large-base",
        "source_url": SOURCE_URL,
        "quote": "Example deploys text-large-base as text-model.",
    }
    values.update(overrides)
    return ModelDeployment(**values)


def collection_policy(**updates) -> Policy:
    values = {
        "provider": "Example",
        "service": "Example Text API",
        "category": "text",
        "provider_domain": "example.com",
        "service_key": "example-text",
        "api_url": "https://api.example.com/v1",
        "docs_url": "https://example.com/docs",
        "free_type": "ongoing",
        "quota": "1000",
        "quota_unit": "requests",
        "refresh_cycle": "monthly",
        "claim_conditions": "free signup",
        "payment_required": False,
        "payment_method_required": False,
        "status": "pending",
    }
    values.update(updates)
    return Policy(**values)


def report_source(**updates) -> MessageSource:
    values = {
        "url": SOURCE_URL,
        "title": "Free API",
        "excerpt": "Free API for developers: 1000 requests per month.",
        "source_type": "community",
        "access": "feed",
        "source_id": "source-1",
        "external_id": "entry-1",
    }
    values.update(updates)
    return MessageSource(**values)


def report(policy: Policy, **updates) -> CollectedMessage:
    values = {
        "policy": policy,
        "offer_key": "default",
        "title": f"{policy.service} free API",
        "summary": "Free API opportunity with a documented quota.",
        "sources": [report_source()],
    }
    values.update(updates)
    return CollectedMessage(**values)


def collect(repository, messages, task_id, *, now=BASE_TIME):
    run = completed_run(task_id, now=now)
    repository.save_run(run)
    batch = ResearchBatch(messages=list(messages))
    events = repository.apply_messages(batch, run, now)
    return run, events, batch


def checked(repository, policy, task_id, *, now=BASE_TIME):
    run = completed_run(task_id, now=now)
    repository.save_run(run)
    changes = repository.apply_batch(ResearchBatch(resources=[policy]), run, now)
    return run, changes


def state(etag: str = 'W/"v1"', **updates) -> SourceState:
    values = {
        "source_id": "source-1",
        "last_checked_at": BASE_TIME,
        "last_success_at": BASE_TIME,
        "status": "ok",
        "etag": etag,
        "last_modified": "Mon, 10 Nov 2026 09:00:00 GMT",
        "config_hash": "cfg-v1",
        "entry_count": 1,
        "next_check_at": BASE_TIME + timedelta(days=1),
    }
    values.update(updates)
    return SourceState(**values)


def snapshot(identifier: str, *, previous_id: str | None = None, **updates):
    values = {
        "id": identifier,
        "source_id": "source-1",
        "url": FEED_URL,
        "fetched_at": BASE_TIME,
        "raw_content": "<rss><item>Free API</item></rss>",
        "content_type": "application/rss+xml",
        "text": "Free API for developers",
        "links": ["https://news.example.com/free-api"],
        "raw_hash": "raw-1",
        "normalized_hash": "norm-1",
        "config_hash": "cfg-v1",
        "previous_id": previous_id,
    }
    values.update(updates)
    return SourceSnapshot(**values)


def entry(*, content: str = "Free API v1", content_hash: str = "hash-1", **updates):
    values = {
        "source_id": "source-1",
        "external_id": "entry-1",
        "url": SOURCE_URL,
        "title": "Free API",
        "content": content,
        "published_at": BASE_TIME,
        "first_seen_at": BASE_TIME,
        "last_seen_at": BASE_TIME,
        "content_hash": content_hash,
        "raw_content": f"<item>{content}</item>",
        "run_id": "run-1",
    }
    values.update(updates)
    return SourceEntry(**values)


def test_raw_entry_commit_is_idempotent_and_same_id_revision_is_explicit(repository):
    source = SourceDefinition(
        id="source-1",
        name="Example feed",
        url=FEED_URL,
        kind="feed",
        categories=[Category.TEXT],
    )
    repository.save_source_definition(source)
    first = entry()
    persisted = repository.commit_source_scan(state(), [first], snapshot("snap-1"))
    (saved,) = persisted
    assert saved.id == first.id
    assert saved.revision == 1
    assert saved.first_seen_at == BASE_TIME
    assert repository.get_source_entry("source-1", "entry-1") == saved

    # The same observation again is a no-op rather than a new version.
    again = repository.commit_source_scan(
        state(etag='W/"v2"'), [first], snapshot("snap-2", previous_id="snap-1")
    )
    assert again[0].id == first.id
    assert again[0].revision == 1
    assert again[0].first_seen_at == BASE_TIME

    # A changed content hash is a real revision on the same external identity.
    match = RuleMatch(rule_id="rule-1", field="title", action="tag", label="关注")
    changed = entry(
        content="Free API v2",
        content_hash="hash-2",
        last_seen_at=BASE_TIME + timedelta(hours=1),
        rule_matches=[match],
        priority=7,
        needs_review=True,
    )
    revised = repository.commit_source_scan(state(), [changed], snapshot("snap-3"))
    assert revised[0].id == first.id
    assert revised[0].revision == 2
    assert revised[0].first_seen_at == BASE_TIME
    assert revised[0].rule_matches == [match]
    assert revised[0].priority == 7
    assert revised[0].needs_review is True

    # Rule replay may only re-annotate; it must not pretend content changed.
    replayed = changed.model_copy(
        update={
            "rule_matches": [],
            "priority": 0,
            "needs_review": False,
            "last_seen_at": BASE_TIME + timedelta(hours=2),
        }
    )
    annotated = repository.commit_source_scan(state(), [replayed])
    assert annotated[0].id == first.id
    assert annotated[0].revision == 2
    assert annotated[0].rule_matches == []
    assert annotated[0].priority == 0


def test_snapshot_versions_and_listing_preserve_original_evidence(repository):
    first = snapshot("snap-1")
    second = snapshot(
        "snap-2",
        previous_id="snap-1",
        fetched_at=BASE_TIME + timedelta(hours=1),
        text_diff="- old line\n+ new line",
        added_links=["https://news.example.com/new"],
        removed_links=["https://news.example.com/old"],
        normalized_hash="norm-2",
    )
    repository.commit_source_scan(state(), [entry()], first)
    repository.commit_source_scan(state(), [entry()], second)
    assert repository.get_source_snapshot("snap-1") == first
    latest = repository.list_source_snapshots("source-1")
    assert [item.id for item in latest] == ["snap-2", "snap-1"]
    assert latest[0].previous_id == "snap-1"
    assert latest[0].text_diff == "- old line\n+ new line"
    assert latest[0].raw_content == first.raw_content


def test_failed_scan_keeps_previous_state_entries_and_snapshot(repository):
    good_state = state()
    original = entry()
    original_snapshot = snapshot("snap-good")
    repository.commit_source_scan(good_state, [original], original_snapshot)

    bad_state = state(etag='W/"bad"')
    bad_snapshot = snapshot("snap-bad")
    wrong = original.model_copy(update={"source_id": "other-source"})
    with pytest.raises(ValueError):
        repository.commit_source_scan(bad_state, [wrong], bad_snapshot)

    with pytest.raises(ValueError):
        repository.commit_source_scan(
            bad_state, [original], snapshot("snap-other", source_id="other-source")
        )

    assert repository.get_source_state("source-1") == good_state
    assert repository.get_source_snapshot("snap-bad") is None
    assert repository.get_source_entry("source-1", "entry-1").content == "Free API v1"
    assert len(repository.list_source_entries("source-1")) == 1


def test_existing_database_receives_source_tables_by_append_migration(repository):
    with sqlite3.connect(repository.db_path) as connection:
        for table in (
            "source_snapshots",
            "source_entries",
            "source_states",
            "source_definitions",
        ):
            connection.execute(f"DROP TABLE IF EXISTS {table}")
        connection.execute("PRAGMA user_version = 5")

    reopened = Repository(repository.data_dir)
    with sqlite3.connect(reopened.db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "source_definitions",
        "source_states",
        "source_entries",
        "source_snapshots",
    } <= tables
    source = SourceDefinition(
        id="source-1", name="Example feed", url=FEED_URL, kind="feed"
    )
    reopened.save_source_definition(source)
    assert reopened.list_source_definitions() == [source]


def test_stored_source_overrides_configured_defaults_without_losing_review(repository):
    configured = SourceDefinition(
        id="source-1", name="Example feed", url=FEED_URL, kind="feed"
    )
    reviewed = configured.model_copy(
        update={"enabled": False, "review_reason": "站点改版", "reopen_if": "恢复稳定订阅"}
    )
    repository.save_source_definition(reviewed)
    extra = SourceDefinition(
        id="source-2",
        name="Legacy source",
        url="https://catalog.example.com/models.json",
        kind="catalog",
        source_type="catalog",
    )
    repository.save_source_definition(extra)

    merged = repository.list_source_definitions([configured])
    assert [item.id for item in merged] == ["source-1", "source-2"]
    assert merged[0].enabled is False
    assert merged[0].review_reason == "站点改版"
    assert merged[0].reopen_if == "恢复稳定订阅"


def test_malformed_optional_fact_is_dropped_without_rejecting_the_message(repository):
    policy = collection_policy(
        quota_facts=[
            {
                "amount": 1000,
                "unit": "requests",
                "source_url": SOURCE_URL,
                "quote": "Free tier: 500 requests per month.",
            }
        ],
        model_deployments=[
            {
                "provider": "Example",
                "model_id": "ghost-model",
                "base_model": "text-large-base",
                "source_url": SOURCE_URL,
                "quote": "Example deploys text-large-base.",
            }
        ],
    )
    assert policy.quota_facts == []
    assert policy.model_deployments == []
    assert len(policy.fact_warnings) == 2
    assert all("已忽略" in warning for warning in policy.fact_warnings)

    _run, events, batch = collect(repository, [report(policy)], "malformed-facts")
    assert batch.failures == []
    assert batch.notes == []
    assert len(events) == 1
    (stored,) = repository.list_messages()
    assert stored.policy.fact_warnings == policy.fact_warnings
    assert stored.sources[0].source_id == "source-1"
    assert stored.sources[0].access == "feed"


def test_reordered_quota_evidence_does_not_create_a_change_but_scope_does(repository):
    image = quota(amount=200, unit="images", scope="image", model_ids=[])
    policy = collection_policy(quota_facts=[quota(), image])
    _, first, batch = collect(repository, [report(policy)], "quota-order-1")
    assert len(first) == 1 and batch.failures == []

    reordered = collection_policy(quota_facts=[image, quota()])
    _, second, batch = collect(
        repository, [report(reordered)], "quota-order-2", now=BASE_TIME + timedelta(hours=1)
    )
    assert second == []
    assert batch.failures == []
    (stored,) = repository.list_messages()
    assert {fact.scope for fact in stored.policy.quota_facts} == {"text", "image"}

    scoped = quota(scope="image-only")
    changed = collection_policy(quota_facts=[scoped, image])
    _, third, _ = collect(
        repository, [report(changed)], "quota-scope-3", now=BASE_TIME + timedelta(hours=2)
    )
    assert [event.kind for event in third] == ["changed"]
    assert "结构化额度" in render_briefing(
        completed_run("quota-scope-3", now=BASE_TIME + timedelta(hours=2)),
        [],
        [],
        [],
        messages=repository.list_messages(),
    )


def test_unknown_optional_facts_do_not_erase_known_strict_evidence(repository):
    first = official_policy(
        quota_facts=[quota()],
        model_deployments=[deployment()],
    )
    checked(repository, first, "facts-1")
    (before,) = repository.list_resources()
    assert before.quota_facts == [quota()]
    assert before.model_deployments == [deployment()]

    later = BASE_TIME + timedelta(hours=2)
    second = revise_policy(
        first,
        checked_at=later,
        quota_facts=[],
        model_deployments=[],
    )
    _, changes = checked(repository, second, "facts-2", now=later)
    (after,) = repository.list_resources()
    assert changes == []
    assert after.quota_facts == before.quota_facts
    assert after.model_deployments == before.model_deployments

    # A failed check also keeps the last explicit evidence rather than emptying it.
    failed = revise_policy(
        first,
        checked_at=later + timedelta(hours=1),
        check_status="failed",
        failure_reason="network unavailable",
        quota_facts=[],
        model_deployments=[],
    )
    _, failed_changes = checked(
        repository, failed, "facts-3", now=later + timedelta(hours=1)
    )
    (retained,) = repository.list_resources()
    assert failed_changes == []
    assert retained.check_status == "failed"
    assert retained.quota_facts == before.quota_facts
    assert retained.model_deployments == before.model_deployments


def test_reordered_deployment_evidence_is_semantically_stable(repository):
    image = deployment(
        model_id="image-model",
        base_model="image-large-base",
        quote="Example deploys image-large-base as image-model.",
    )
    text = deployment()
    first = official_policy(model_deployments=[text, image])
    checked(repository, first, "deploy-1")
    (before,) = repository.list_resources()
    later = BASE_TIME + timedelta(hours=2)
    second = revise_policy(first, checked_at=later, model_deployments=[image, text])
    _, changes = checked(repository, second, "deploy-2", now=later)
    (after,) = repository.list_resources()
    assert changes == []
    assert {item.model_dump_json() for item in after.model_deployments} == {
        item.model_dump_json() for item in before.model_deployments
    }


def test_briefing_shows_scope_conditions_models_and_gap_stop_reason(repository):
    policy = collection_policy(
        quota_facts=[quota()],
        model_deployments=[deployment()],
        fact_warnings=["quota_facts[0]：可选事实缺少有效原文支持，已忽略"],
    )
    run, events, _ = collect(repository, [report(policy)], "briefing-facts")
    run.research_traces = [
        ResearchTrace(
            gap_id="gap-1",
            category=Category.TEXT,
            query="Example free trial credits",
            goal="确认免费试用额度",
            trigger_url=SOURCE_URL,
            source_ids=["source-1"],
            result_urls=["https://example.com/pricing"],
            new_evidence_urls=["https://example.com/pricing"],
            stop_reason="no_new_evidence",
            search_calls=1,
        )
    ]
    markdown = visible(render_briefing(run, [], [], [], messages=events))
    assert "结构化额度" in markdown
    assert "1000 requests / month" in markdown
    assert "作用域：text" in markdown
    assert "适用模型：text-model" in markdown
    assert "模型部署：Example / text-model（基础模型：text-large-base）" in markdown
    assert "可选事实提示" in markdown
    assert "来源身份：source-1 / entry-1" in markdown
    assert "订阅原始条目" in markdown
    assert "## 证据补搜" in markdown
    assert "确认免费试用额度" in markdown
    assert "未发现新增证据" in markdown
    assert "https://example.com/pricing" in markdown


def product_report(access_mode: str, excerpt: str, **policy_updates) -> CollectedMessage:
    policy = collection_policy(
        service="WorkBuddy",
        service_key="workbuddy",
        api_url="未说明",
        docs_url="未说明",
        access_mode=access_mode,
        **policy_updates,
    )
    return report(
        policy,
        title="WorkBuddy 免费积分",
        summary="WorkBuddy 每月赠送免费积分，可在桌面端使用。",
        sources=[
            report_source(
                url="https://www.workbuddy.ai/pricing",
                title="WorkBuddy 定价",
                excerpt=excerpt,
            )
        ],
    )


def test_source_backed_product_credit_message_is_accepted_without_api_evidence():
    message = product_report(
        "product", "WorkBuddy 每月赠送免费积分，可在桌面端使用，无需支付。"
    )
    assert message.policy.api_url == "未说明"
    assert message.policy.docs_url == "未说明"
    assert message_problem(message) == ""


def test_product_credit_message_labeled_api_is_rejected():
    message = product_report(
        "api", "WorkBuddy 每月赠送免费积分，可在桌面端使用，无需支付。"
    )
    assert message_problem(message) == "来源未明确说明免费 API 机会"


def test_product_mode_still_rejects_explicit_purchase_or_top_up():
    message = product_report("product", "WorkBuddy 提供免费积分，但需充值后才能使用。")
    assert message_problem(message) == "来源说明需实际付款、购买或充值，非免费机会"


def test_product_credit_message_is_stored_as_a_product_offer(repository):
    message = product_report(
        "product", "WorkBuddy 每月赠送免费积分，可在桌面端使用，无需支付。"
    )
    _, events, batch = collect(repository, [message], "product-credit-offer")
    assert batch.notes == []
    (event,) = events
    stored = repository.get_resource(event.resource_id)
    assert stored is not None
    assert stored.access_mode == "product"
    assert stored.api_url == "未说明"


def test_existing_message_resource_follows_the_reported_access_mode(repository):
    first = product_report("unknown", "WorkBuddy 提供免费 API，每月 1000 次调用。")
    _, events, batch = collect(repository, [first], "mode-unknown")
    assert batch.notes == []
    (event,) = events
    stored = repository.get_resource(event.resource_id)
    assert stored is not None
    assert stored.access_mode == "unknown"

    second = product_report(
        "product", "WorkBuddy 每月赠送免费积分，可在桌面端使用，无需支付。"
    )
    _, events, batch = collect(repository, [second], "mode-product")
    assert batch.notes == []
    assert len(events) == 1
    stored = repository.get_resource(event.resource_id)
    assert stored is not None
    assert stored.access_mode == "product"

