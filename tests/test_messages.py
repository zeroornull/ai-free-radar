"""Persistence acceptance for source-backed free API collection news."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any, Literal

import pytest
from domain_fixtures import BASE_TIME, completed_run, official_policy

from aifreeradar.models import (
    Category,
    CollectedMessage,
    Evidence,
    MessageSource,
    Policy,
    ResearchBatch,
    Resource,
    ResourceStatus,
    Scope,
)
from aifreeradar.storage import MIGRATIONS, Repository


@pytest.fixture
def repository(tmp_path):
    return Repository(tmp_path / "data")


def source(
    url="https://news.example.com/free-api",
    *,
    excerpt="Free API for developers: 1000 requests per month.",
    source_type: Literal["official", "community", "github", "search"] = "search",
    access: Literal["page", "snippet"] = "page",
    title="",
):
    return MessageSource(
        url=url, title=title, excerpt=excerpt, source_type=source_type, access=access
    )


def collection_policy(
    *,
    category="text",
    provider="News Provider",
    service=None,
    service_key=None,
    quota="1000",
    free_type="ongoing",
    payment_required: bool | None = False,
    api_url="https://api.news.example.com/v1",
    docs_url="https://news.example.com/docs",
    expires_at=None,
    **updates,
):
    values = {
        "provider": provider,
        "service": service or f"News {str(category).title()} API",
        "category": category,
        "provider_domain": "news.example.com",
        "service_key": service_key or f"news-{category}",
        "api_url": api_url,
        "docs_url": docs_url,
        "free_type": free_type,
        "quota": quota,
        "quota_unit": "requests",
        "claim_conditions": "免费注册即用，无需充值",
        "payment_required": payment_required,
        "payment_method_required": None,
        "expires_at": expires_at,
        "status": "pending",
    }
    values.update(updates)
    return Policy(**values)


def collected(
    policy,
    *,
    offer_key="default",
    summary="Free API opportunity with a documented free quota.",
    sources=None,
    ended=False,
    end_reason="",
):
    items = list(sources) if sources is not None else [source()]
    if ended and end_reason:
        items = [
            item.model_copy(
                update={"excerpt": f"{item.excerpt} {end_reason}".strip()}
            )
            for item in items
        ]
    return CollectedMessage(
        policy=policy,
        offer_key=offer_key,
        title=f"{policy.service} 免费接口",
        summary=summary,
        sources=items,
        ended=ended,
        end_reason=end_reason,
    )


def apply(repository, messages, task_id, *, now=BASE_TIME, scope=None):
    run = completed_run(task_id, now=now, scope=scope)
    repository.save_run(run)
    batch = ResearchBatch(messages=list(messages))
    events = repository.apply_messages(batch, run, now)
    return run, events, batch


def strict_apply(repository, policy, task_id, *, now=BASE_TIME):
    run = completed_run(task_id, now=now)
    repository.save_run(run)
    changes = repository.apply_batch(ResearchBatch(resources=[policy]), run, now)
    return run, changes


def test_source_requires_safe_http_link_and_nonempty_excerpt():
    with pytest.raises(ValueError):
        MessageSource(url="ftp://news.example.com/api", excerpt="free api")
    with pytest.raises(ValueError):
        MessageSource(url="https://user:secret@news.example.com/api", excerpt="free api")
    with pytest.raises(ValueError):
        MessageSource(url="javascript:alert(1)", excerpt="free api")
    with pytest.raises(ValueError):
        MessageSource(url="https://news.example.com/api", excerpt="   ")
    with pytest.raises(ValueError):
        CollectedMessage(
            policy=collection_policy(),
            title="Free API",
            summary="Free API",
            sources=[],
        )


def test_collection_creates_unverified_resource_with_separate_report(repository):
    message = collected(collection_policy())
    run, events, _ = apply(repository, [message], "collect-1")

    (item,) = events
    assert item.kind == "new"
    assert item.task_id == run.id
    (resource,) = repository.list_resources()
    assert resource.id == item.resource_id
    # Claims stay in the report channel; no verification is implied.
    assert resource.status == ResourceStatus.PENDING
    assert resource.last_success_at is None
    assert resource.recommended_at is None
    assert resource.evidence == []
    assert resource.quota == "未说明"
    (report,) = resource.messages
    assert report.offer_key == "default"
    assert report.policy.quota == "1000"
    assert [entry.id for entry in repository.list_messages()] == [item.id]


def test_repost_merges_sources_without_duplicate_event(repository):
    message = collected(collection_policy())
    apply(repository, [message], "collect-1")
    repost = collected(
        collection_policy(),
        sources=[
            source(
                url="https://community.example.com/repost",
                source_type="community",
                excerpt="Community repost confirms the free API quota.",
            )
        ],
    )
    _, events, _ = apply(repository, [repost], "collect-2", now=BASE_TIME + timedelta(hours=1))

    assert events == []
    (resource,) = repository.list_resources()
    (report,) = resource.messages
    assert {item.url for item in report.sources} == {
        "https://news.example.com/free-api",
        "https://community.example.com/repost",
    }
    (item,) = repository.list_messages()
    assert item.discovered_at == BASE_TIME, "source-only merge must not bump event time"
    assert len(item.sources) == 2


def test_substantive_change_creates_event_but_title_and_summary_tweaks_do_not(repository):
    apply(repository, [collected(collection_policy())], "collect-1")
    changed = collected(
        collection_policy(quota="2500"),
        summary="Rewritten free API headline mentioning the larger quota.",
    )
    _, events, _ = apply(repository, [changed], "collect-2", now=BASE_TIME + timedelta(hours=1))
    (event,) = events
    assert event.kind == "changed"
    assert event.policy.quota == "2500"

    paraphrase = collected(
        collection_policy(quota="2500"),
        summary="Entirely different wording for the same free API benefit.",
    )
    paraphrase = paraphrase.model_copy(update={"title": "Another headline"})
    _, no_events, _ = apply(
        repository, [paraphrase], "collect-3", now=BASE_TIME + timedelta(hours=2)
    )
    assert no_events == []
    assert [entry.kind for entry in repository.list_messages(include_ended=True)] == [
        "changed",
        "new",
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [("quota", "未说明"), ("claim_conditions", "未说明"), ("free_type", "unknown")],
)
def test_unknown_incoming_values_never_erase_known_reported_facts(repository, field, value):
    baseline: dict[str, Any] = {"quota": "1000", "claim_conditions": "免费注册即用"}
    apply(
        repository,
        [collected(collection_policy(**baseline))],
        "collect-1",
    )
    sparse = collected(
        collection_policy(**(baseline | {field: value})),
        summary="Sparse repost without repeating the benefit details.",
    )
    _, events, _ = apply(repository, [sparse], "collect-2", now=BASE_TIME + timedelta(hours=1))

    assert events == []
    (resource,) = repository.list_resources()
    (report,) = resource.messages
    assert report.policy.quota == "1000"
    assert report.policy.claim_conditions == "免费注册即用"
    assert report.policy.free_type == "ongoing"
    assert len(repository.list_messages()) == 1


def test_ended_offer_is_hidden_by_default_but_kept_in_history(repository):
    _, first, _ = apply(repository, [collected(collection_policy())], "collect-1")
    ended = collected(
        collection_policy(),
        ended=True,
        end_reason="官方公告活动已停止",
    )
    _, events, _ = apply(repository, [ended], "collect-2", now=BASE_TIME + timedelta(days=2))

    (event,) = events
    assert event.kind == "expired"
    assert event.ended is True
    assert repository.list_messages() == []
    history = repository.list_messages(include_ended=True)
    assert [entry.kind for entry in history] == ["expired", "new"]
    assert {entry.resource_id for entry in history} == {first[0].resource_id}
    (resource,) = repository.list_resources()
    (report,) = resource.messages
    assert report.ended is True


def test_stale_repost_does_not_restore_but_sourced_renewal_does(repository):
    apply(repository, [collected(collection_policy())], "collect-1")
    ended = collected(collection_policy(), ended=True, end_reason="官方公告活动已停止")
    apply(repository, [ended], "collect-2", now=BASE_TIME + timedelta(days=2))

    _, stale_events, _ = apply(
        repository,
        [collected(collection_policy())],
        "collect-3",
        now=BASE_TIME + timedelta(days=3),
    )
    assert stale_events == []
    (resource,) = repository.list_resources()
    (report,) = resource.messages
    assert report.ended is True
    assert report.end_reason == "官方公告活动已停止"

    expiry = BASE_TIME + timedelta(days=30)
    renewed = collected(
        collection_policy(expires_at=expiry),
        summary="Free API renewed with a new expiry date.",
        sources=[
            source(
                excerpt=(
                    "Free API available again; the offer is extended until "
                    f"{expiry.date().isoformat()}."
                )
            )
        ],
    )
    _, events, _ = apply(repository, [renewed], "collect-4", now=BASE_TIME + timedelta(days=3))
    (event,) = events
    assert event.kind == "restored"
    assert event.ended is False
    assert len(repository.list_messages()) == 3


def test_sourced_past_expiry_ends_offer_while_age_alone_never_does(repository):
    past = BASE_TIME - timedelta(days=1)
    limited = collected(
        collection_policy(free_type="limited", expires_at=past),
        sources=[
            source(
                excerpt=f"Free API offer is valid through {past.date().isoformat()}."
            )
        ],
    )
    _, events, _ = apply(repository, [limited], "collect-1")

    (event,) = events
    assert event.kind == "expired"
    assert event.end_reason
    assert repository.list_messages() == []
    assert len(repository.list_messages(include_ended=True)) == 1

    later = BASE_TIME + timedelta(days=400)
    still_open = collected(
        collection_policy(free_type="limited"),
        sources=[source(excerpt="Free API available again at no cost.")],
    )
    _, events, _ = apply(repository, [still_open], "collect-2", now=later)
    (event,) = events
    assert event.kind == "restored"
    assert len(repository.list_messages()) == 2


def test_distinct_campaigns_and_categories_never_coalesce(repository):
    text = collected(collection_policy(category="text"), offer_key="free-tier")
    banner = collected(
        collection_policy(category="text"),
        offer_key="banner-promo",
        summary="Promotional free API campaign with the same quota.",
    )
    image = collected(collection_policy(category="image"), offer_key="free-tier")
    _, events, _ = apply(repository, [text, banner, image], "collect-1")

    assert len(events) == 3
    resources = repository.list_resources()
    assert len(resources) == 2
    text_resource = next(
        item for item in resources if item.category == Category.TEXT
    )
    assert {message.offer_key for message in text_resource.messages} == {
        "free-tier",
        "banner-promo",
    }
    image_resource = next(
        item for item in resources if item.category == Category.IMAGE
    )
    assert image_resource.id != text_resource.id
    assert len(repository.list_messages()) == 3


def test_scope_and_ignored_resources_are_excluded_from_collection(repository):
    apply(repository, [collected(collection_policy())], "collect-1")
    (resource,) = repository.list_resources()
    repository.apply_review(resource.id, "ignore", now=BASE_TIME)
    _, events, _ = apply(
        repository,
        [collected(collection_policy(), offer_key="second-offer")],
        "collect-2",
        now=BASE_TIME + timedelta(hours=1),
    )
    assert events == []
    assert repository.list_messages() == []
    assert repository.list_messages(include_ended=True) == []
    assert len(repository.list_resources()) == 1

    _, out_events, batch = apply(
        repository,
        [collected(collection_policy(category="image"))],
        "collect-3",
        scope=Scope(categories=[Category.TEXT]),
    )
    assert out_events == []
    assert any("超出本次范围" in reason for reason in batch.failures)


@pytest.mark.parametrize("kind", ["paid", "web-only"])
def test_paid_or_web_only_messages_are_never_persisted(repository, kind):
    if kind == "paid":
        message = collected(
            collection_policy(payment_required=True),
            sources=[source(excerpt="Free API requires payment or purchase first.")],
        )
    else:
        message = collected(
            collection_policy(),
            sources=[source(excerpt="Free browser chat tool only; no API, web-only.")],
        )
    _, events, _ = apply(repository, [message], "collect-1")

    assert events == []
    assert repository.list_resources() == []
    assert repository.list_messages(include_ended=True) == []


def test_snippet_sources_are_attributed_without_claiming_page_access(repository):
    message = collected(
        collection_policy(),
        sources=[
            source(
                source_type="search",
                access="snippet",
                excerpt="Search snippet: free API, 1000 requests per month.",
            )
        ],
    )
    apply(repository, [message], "collect-1")

    (item,) = repository.list_messages()
    assert item.sources[0].access == "snippet"
    assert item.sources[0].source_type == "search"
    assert item.sources[0].excerpt.startswith("Search snippet:")


def test_list_messages_filters_and_orders_newest_first(repository):
    text = collected(collection_policy(category="text"))
    image = collected(collection_policy(category="image"))
    _, _, _ = apply(repository, [text, image], "collect-1")
    change = collected(collection_policy(category="text", quota="5000"))
    apply(repository, [change], "collect-2", now=BASE_TIME + timedelta(hours=1))

    feed = repository.list_messages()
    assert [item.kind for item in feed] == ["changed", "new", "new"]
    assert feed[0].task_id == "collect-2"
    assert {item.task_id for item in feed[1:]} == {"collect-1"}
    image_feed = repository.list_messages(category=Category.IMAGE)
    assert [item.policy.category for item in image_feed] == [Category.IMAGE]
    task_feed = repository.list_messages(task_id="collect-1")
    assert {item.task_id for item in task_feed} == {"collect-1"}
    assert len(task_feed) == 2


def test_collection_never_overwrites_verified_policy_facts(repository):
    verified = official_policy()
    strict_apply(repository, verified, "verify-1", now=BASE_TIME)
    (before,) = repository.list_resources()

    claimed = collected(
        collection_policy(
            provider="Fixture Provider",
            service="Fixture Text API",
            provider_domain="fixture-provider.test",
            service_key="fixture-text-api",
            quota="99999",
        )
    )
    _, events, _ = apply(repository, [claimed], "collect-1", now=BASE_TIME + timedelta(hours=1))

    (event,) = events
    assert event.kind == "new"
    (after,) = repository.list_resources()
    assert after.id == before.id
    assert after.quota == verified.quota
    assert after.status == ResourceStatus.ACTIVE
    assert after.evidence == before.evidence
    assert after.last_success_at == before.last_success_at
    assert (after.messages[0].policy.quota, after.messages[0].policy.free_type) == (
        "99999",
        "ongoing",
    )
    assert after.recommended_at == before.recommended_at


def legacy_evidence(quote="Legacy saved official statement: 5000 free requests per month."):
    return Evidence(
        field="quota",
        url="https://legacy.example/docs",
        quote=quote,
        source_type="official",
        checked_at=BASE_TIME,
        official_domain="legacy.example",
    )


def legacy_resource(
    *,
    service="Legacy Text API",
    status="active",
    payment_required=False,
    evidence_items=None,
    **updates,
):
    values = {
        "provider": "Legacy Provider",
        "service": service,
        "category": Category.TEXT,
        "provider_domain": "legacy.example",
        "service_key": "legacy-text",
        "api_url": "https://legacy.example/api",
        "docs_url": "https://legacy.example/docs",
        "free_type": "ongoing",
        "quota": "5000",
        "quota_unit": "requests",
        "claim_conditions": "免费注册即用",
        "payment_required": payment_required,
        "payment_method_required": False,
        "status": status,
        "first_seen_at": BASE_TIME - timedelta(days=10),
        "last_checked_at": BASE_TIME,
        "last_success_at": BASE_TIME,
        "evidence": [legacy_evidence()] if evidence_items is None else list(evidence_items),
    }
    values.update(updates)
    return Resource(**values)


def build_v4_database(data_dir, *resources):
    data_dir.mkdir(parents=True)
    connection = sqlite3.connect(data_dir / "radar.sqlite3")
    try:
        for script in MIGRATIONS[:4]:
            connection.executescript(script)
        connection.execute("PRAGMA user_version = 4")
        for resource in resources:
            connection.execute(
                "INSERT INTO resources(id, provider_domain, service_key, category, "
                "status, china_policy, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    resource.id,
                    resource.provider_domain,
                    resource.service_key,
                    str(resource.category),
                    str(resource.status),
                    str(resource.china_policy),
                    resource.model_dump_json(),
                ),
            )
        connection.commit()
    finally:
        connection.close()


def test_v4_database_backfills_source_backed_policies_exactly_once(tmp_path):
    legacy = legacy_resource()
    no_source = legacy_resource(
        service="No Source API", service_key="no-source", evidence_items=[]
    )
    paid = legacy_resource(
        service="Paid API", service_key="paid", payment_required=True
    )
    expired = legacy_resource(
        service="Ended API",
        service_key="ended",
        status="expired",
        expiry_notes="官方已停止赠额",
    )
    data_dir = tmp_path / "v4"
    build_v4_database(data_dir, legacy, no_source, paid, expired)

    repository = Repository(data_dir)
    history = repository.list_messages(include_ended=True)
    assert {item.resource_id for item in history} == {legacy.id, expired.id}
    assert {item.kind for item in history} == {"new", "expired"}
    assert {item.resource_id for item in repository.list_messages()} == {legacy.id}

    preserved = repository.get_resource(legacy.id)
    assert preserved is not None
    assert preserved.quota == legacy.quota
    assert preserved.evidence == legacy.evidence
    assert preserved.status == ResourceStatus.ACTIVE
    assert preserved.last_success_at == legacy.last_success_at
    (report,) = preserved.messages
    assert report.sources[0].excerpt == legacy.evidence[0].quote
    no_source_resource = repository.get_resource(no_source.id)
    paid_resource = repository.get_resource(paid.id)
    assert no_source_resource is not None and no_source_resource.messages == []
    assert paid_resource is not None and paid_resource.messages == []

    reopened = Repository(data_dir)
    assert len(reopened.list_messages(include_ended=True)) == 2
    reopened_legacy = reopened.get_resource(legacy.id)
    assert reopened_legacy is not None and len(reopened_legacy.messages) == 1
    with reopened._connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
        assert connection.execute(
            "SELECT value FROM settings_meta WHERE key = 'messages_backfilled_v2'"
        ).fetchone()[0] == "1"


def test_unknown_terms_and_missing_entry_are_collectable_with_real_free_api_source(repository):
    policy = collection_policy(
        free_type="unknown", quota="未说明", payment_required=None,
        api_url="未说明", docs_url="未说明", claim_conditions="未说明",
    )
    _, events, batch = apply(repository, [collected(policy)], "collect-unknown")
    assert len(events) == 1
    assert batch.failures == []
    assert events[0].policy.payment_required is None


def test_summary_and_policy_cannot_invent_free_support_for_an_unrelated_source(repository):
    message = collected(
        collection_policy(),
        sources=[source(excerpt="Developer API documentation and integration examples.")],
    )
    _, events, batch = apply(repository, [message], "unsupported-free")
    assert events == []
    assert repository.list_messages(include_ended=True) == []
    assert batch.notes


def test_rate_limit_payment_status_with_free_wait_option_is_not_actual_payment(repository):
    message = collected(
        collection_policy(payment_required=None),
        sources=[source(excerpt=(
            "Free image API, no signup. Beyond the rate limit you get 402 Payment Required. "
            "Wait for the next free slot, or optionally pay to bypass the rate limit."
        ))],
    )
    _, events, _ = apply(repository, [message], "optional-rate-limit-payment")
    assert len(events) == 1