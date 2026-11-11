"""Behavioral acceptance for free-policy decisions and durable business records."""

from __future__ import annotations

import re
import sqlite3
from datetime import timedelta

import pytest
from domain_fixtures import (
    BASE_TIME,
    CATEGORIES,
    QUOTA_UNITS,
    completed_run,
    official_policy,
    revise_policy,
)

from aifreeradar.briefing import render_briefing
from aifreeradar.models import Category, LeadDiscovery, ResearchBatch, Scope
from aifreeradar.storage import MIGRATIONS, Repository


@pytest.fixture
def repository(tmp_path):
    return Repository(tmp_path / "data")


def apply(repository, policies, task_id, *, now=BASE_TIME, scope=None, failures=None):
    run = completed_run(task_id, now=now, scope=scope)
    repository.save_run(run)
    batch = ResearchBatch(resources=policies, failures=failures or [])
    changes = repository.apply_batch(batch, run, now)
    return run, changes


def section(markdown, title):
    """Extract a required level-two section, without depending on list formatting."""
    for block in re.split(r"(?m)^## ", markdown)[1:]:
        heading, _, body = block.partition("\n")
        if title in heading:
            return visible(body)
    raise AssertionError(f"Missing briefing section {title!r}:\n{markdown}")


def visible(markdown):
    return re.sub(r"\\([^\w\s])", r"\1", markdown)


def remove_evidence(policy, *fields):
    return policy.model_copy(
        deep=True,
        update={"evidence": [item for item in policy.evidence if item.field not in fields]},
    )


@pytest.mark.parametrize("free_type", ["ongoing", "limited"])
def test_official_zero_payment_policy_is_active_with_units_sources_and_times(repository, free_type):
    policy = official_policy(free_type=free_type)
    run, changes = apply(repository, [policy], f"initial-{free_type}")
    (resource,) = repository.list_resources()

    assert resource.status == "active"
    assert resource.free_type == free_type
    assert resource.payment_required is False
    assert resource.payment_method_required is False
    assert resource.quota == "1000"
    assert resource.quota_unit == "tokens"
    assert resource.models == policy.models
    assert resource.docs_url == policy.docs_url
    assert resource.api_url == policy.api_url
    assert resource.first_seen_at == resource.last_checked_at == BASE_TIME
    assert resource.last_success_at == resource.recommended_at == BASE_TIME
    assert resource.last_task_id == run.id
    assert resource.evidence == policy.evidence
    if free_type == "limited":
        assert resource.expires_at == BASE_TIME + timedelta(days=30)
    assert [change.kind for change in changes] == ["new"]
    markdown = render_briefing(run, [resource], changes, [])
    formal = section(markdown, "新发现")
    assert policy.service in formal
    assert policy.docs_url in formal
    assert policy.quota_unit in formal
    assert policy.evidence[0].url in formal
    assert "未实测调用" in markdown
    assert "未实测" in markdown
    assert "2026-11-10" in formal


@pytest.mark.parametrize("field", ["payment_required", "payment_method_required"])
def test_unknown_payment_flag_without_evidence_stays_pending(repository, field):
    if field == "payment_required":
        policy = official_policy(payment_required=None)
    else:
        policy = official_policy(payment_method_required=None)
    run, changes = apply(repository, [policy], f"payment-{field}-unknown")
    (resource,) = repository.list_resources()
    assert resource.status == "pending"
    assert getattr(resource, field) is None
    assert resource.recommended_at is None
    markdown = render_briefing(run, [resource], changes, [])
    assert resource.service in section(markdown, "待核实")
    formal = next(
        (block for block in re.split(r"(?m)^## ", markdown)[1:] if block.startswith("新发现")), ""
    )
    assert resource.service not in formal


def test_binding_card_without_payment_is_formal_recommendation(repository):
    policy = official_policy(payment_required=False, payment_method_required=True)
    run, changes = apply(repository, [policy], "payment-card-required")
    (resource,) = repository.list_resources()
    assert resource.status == "active"
    assert resource.payment_required is False
    assert resource.payment_method_required is True
    assert resource.recommended_at == BASE_TIME
    markdown = render_briefing(run, [resource], changes, [])
    assert resource.service in section(markdown, "新发现")


def test_actual_payment_requirement_is_not_formal_recommendation(repository):
    policy = official_policy(payment_required=True, payment_method_required=False)
    run, changes = apply(repository, [policy], "payment-required")
    (resource,) = repository.list_resources()
    assert resource.status == "pending"
    assert resource.payment_required is True
    assert resource.recommended_at is None
    markdown = render_briefing(run, [resource], changes, [])
    assert resource.service in section(markdown, "待核实")


@pytest.mark.parametrize("category", CATEGORIES)
def test_all_six_categories_preserve_their_quota_units(repository, category):
    policy = official_policy(
        category=category, service_key=f"fixture-{category}", service=f"Fixture {category} API"
    )
    apply(repository, [policy], f"category-{category}")
    (resource,) = repository.list_resources(category=category)
    assert resource.category == category
    assert resource.quota_unit == QUOTA_UNITS[category]
    assert resource.status == "active"


def test_same_provider_has_six_distinct_api_policies_even_with_shared_name_and_links(repository):
    policies = [
        official_policy(
            category=category,
            service_key=f"service-{category}",
            service="Fixture Unified API",
            quota=str(index + 1),
        )
        for index, category in enumerate(CATEGORIES)
    ]
    _, changes = apply(repository, policies, "six-services")
    resources = repository.list_resources()
    assert len(resources) == len(changes) == 6
    assert len({resource.id for resource in resources}) == 6
    assert {resource.category for resource in resources} == set(CATEGORIES)
    assert {resource.service_key: resource.quota for resource in resources} == {
        policy.service_key: policy.quota for policy in policies
    }
    assert all(resource.status == "active" for resource in resources)


def test_checked_time_and_evidence_order_do_not_duplicate_history_or_recommendation(repository):
    original = official_policy(models=["fixture-model-v1", "fixture-model-v2"])
    apply(repository, [original], "first")
    (before,) = repository.list_resources()
    later = BASE_TIME + timedelta(hours=2)
    refreshed = revise_policy(original, checked_at=later)
    refreshed.evidence.reverse()
    refreshed.models = list(reversed(refreshed.models))
    run, changes = apply(repository, [refreshed], "unchanged", now=later)
    (after,) = repository.list_resources()
    assert after.id == before.id
    assert after.first_seen_at == before.first_seen_at
    assert after.last_checked_at == after.last_success_at == later
    assert after.recommended_at == before.recommended_at
    assert after.evidence == refreshed.evidence
    assert changes == repository.get_changes(run.id) == []
    assert len(repository.history(after.id)) == 1
    markdown = render_briefing(run, [after], changes, [])
    assert "本次无新增或变化" in markdown
    assert after.service not in markdown


@pytest.mark.parametrize("identity", ["stable-key", "explicit-alias", "resource-id"])
def test_names_and_links_can_change_without_losing_stable_resource_identity(repository, identity):
    original = official_policy()
    apply(repository, [original], "before-rename")
    (before,) = repository.list_resources()
    later = BASE_TIME + timedelta(hours=1)
    updates: dict[str, object] = {
        "service": "Fixture Renamed API",
        "api_url": "https://fixture-provider.test/v2/entry",
        "docs_url": "https://fixture-provider.test/new-docs",
    }
    if identity != "stable-key":
        updates.update(service_key="renamed-service", aliases=[original.service_key])
    if identity == "resource-id":
        updates["resource_id"] = before.id
    renamed = revise_policy(original, checked_at=later, **updates)
    _, changes = apply(repository, [renamed], "after-rename", now=later)
    (after,) = repository.list_resources()
    assert after.id == before.id
    assert after.service_key == before.service_key
    assert after.service == updates["service"]
    assert after.docs_url == updates["docs_url"]
    assert after.first_seen_at == before.first_seen_at
    assert after.recommended_at == before.recommended_at
    assert changes == []
    assert len(repository.history(after.id)) == 1
    if identity != "stable-key":
        # Future reports carrying the original identity still find the same record.
        apply(repository, [revise_policy(original, checked_at=later)], "old-name", now=later)
        assert len(repository.list_resources()) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quota", "2500"),
        ("quota_unit", "requests"),
        ("refresh_cycle", "每月 1 日 UTC"),
        ("rate_limit", "2 requests/minute"),
        ("models", ["fixture-model-v2", "fixture-model-v3"]),
        ("claim_conditions", "必须在控制台手动领取；无需支付"),
        ("payment_required", True),
        ("payment_method_required", True),
        ("china_policy", "unsupported"),
        ("region_restrictions", "仅支持测试区域；中国大陆不支持"),
        ("expires_at", BASE_TIME + timedelta(days=60)),
    ],
)
def test_substantive_changes_keep_before_after_time_and_field_evidence(repository, field, value):
    original = official_policy()
    apply(repository, [original], "before-policy-change")
    (old,) = repository.list_resources()
    later = BASE_TIME + timedelta(days=1)
    changed = revise_policy(original, checked_at=later, **{field: value})
    run, changes = apply(repository, [changed], f"change-{field}", now=later)
    (event,) = changes
    (current,) = repository.list_resources()
    assert current.id == old.id
    assert event.kind == "changed"
    assert event.resource_id == old.id
    assert event.task_id == run.id
    assert event.before[field] == original.model_dump(mode="json")[field]
    assert event.after[field] == changed.model_dump(mode="json")[field]
    assert event.discovered_at == later
    assert any(item.field == field and item.checked_at == later for item in event.evidence)
    assert repository.get_changes(run.id) == changes
    assert repository.history(old.id)[-1] == event
    if field == "payment_required":
        assert current.status == "pending"
        assert current.recommended_at == old.recommended_at
    else:
        assert current.status == "active"
        assert current.recommended_at == later
        markdown = render_briefing(run, [current], changes, [])
        assert current.service in section(markdown, "重要变化")
        assert next(item.url for item in event.evidence if item.field == field) in markdown


def test_confirmed_expiry_and_restoration_have_ordered_durable_history(repository):
    expiry = BASE_TIME + timedelta(days=2)
    policy = official_policy(free_type="limited", expires_at=expiry)
    apply(repository, [policy], "initial-limited")
    (original,) = repository.list_resources()
    expiry_run, expired = apply(repository, [policy], "confirmed-expired", now=expiry)
    (resource,) = repository.list_resources()
    assert resource.status == "expired"
    assert resource.id == original.id
    (event,) = expired
    assert event.kind == "expired"
    assert event.before["status"] == "active"
    assert event.after["status"] == "expired"
    assert event.after["expires_at"] == policy.model_dump(mode="json")["expires_at"]
    assert any(item.field == "expires_at" for item in event.evidence)
    markdown = render_briefing(expiry_run, [resource], expired, [])
    assert resource.service in section(markdown, "已失效")

    restored_at = expiry + timedelta(days=1)
    restored_policy = revise_policy(
        policy,
        checked_at=restored_at,
        expires_at=restored_at + timedelta(days=30),
        expiry_notes="官方续期，零支付权益恢复",
    )
    run, restored = apply(repository, [restored_policy], "restored", now=restored_at)
    (current,) = repository.list_resources()
    (event,) = restored
    assert current.id == original.id
    assert current.status == "active"
    assert current.recommended_at == restored_at
    assert event.kind == "restored"
    assert event.before["status"] == "expired"
    assert event.after["status"] == "active"
    assert event.discovered_at == restored_at
    assert any(item.checked_at == restored_at for item in event.evidence)
    assert [event.kind for event in repository.history(current.id)] == [
        "new",
        "expired",
        "restored",
    ]
    assert current.service in section(render_briefing(run, [current], restored, []), "重要变化")


@pytest.mark.parametrize("check_status", ["failed", "incomplete"])
def test_failed_or_incomplete_recheck_preserves_last_confirmed_policy(repository, check_status):
    policy = official_policy()
    apply(repository, [policy], "confirmed")
    (before,) = repository.list_resources()
    later = BASE_TIME + timedelta(days=1)
    failed = revise_policy(
        policy,
        checked_at=later,
        check_status=check_status,
        failure_reason="官方页面连接超时",
        status="expired",
        quota="0",
        models=[],
        evidence=[],
        payment_required=True,
        china_policy="unsupported",
    )
    run, changes = apply(repository, [failed], f"attempt-{check_status}", now=later)
    (after,) = repository.list_resources()
    for field in (
        "id",
        "provider",
        "service",
        "service_key",
        "category",
        "status",
        "free_type",
        "quota",
        "quota_unit",
        "refresh_cycle",
        "rate_limit",
        "models",
        "claim_conditions",
        "payment_required",
        "payment_method_required",
        "china_policy",
        "region_restrictions",
        "expires_at",
        "evidence",
        "first_seen_at",
        "last_success_at",
        "recommended_at",
    ):
        assert getattr(after, field) == getattr(before, field), field
    assert after.check_status == check_status
    assert after.failure_reason == "官方页面连接超时"
    assert after.last_checked_at == later
    assert after.last_task_id == run.id
    assert changes == []
    assert len(repository.history(after.id)) == 1
    markdown = render_briefing(run, [after], [], [failed.failure_reason])
    failure_section = section(markdown, "核查失败")
    assert failed.failure_reason in failure_section
    assert after.service in failure_section
    assert "2026-11-10" in failure_section
    assert "有效" in failure_section


@pytest.mark.parametrize(
    "problem", ["community-only", "empty-quote", "foreign-host", "no-evidence"]
)
def test_unverified_or_thirdparty_evidence_stays_pending(repository, problem):
    policy = official_policy()
    if problem == "no-evidence":
        policy.evidence = []
    else:
        for item in policy.evidence:
            if problem == "community-only":
                item.source_type = "community"
            elif problem == "empty-quote":
                item.quote = "   "
            elif problem == "foreign-host":
                item.url = "https://community.test/free-api"
                # A claimed official_domain must not authenticate an unrelated URL.
                item.official_domain = policy.provider_domain
    run, changes = apply(repository, [policy], f"unverified-{problem}")
    (resource,) = repository.list_resources()
    assert resource.status == "pending"
    assert resource.china_policy == "unknown"
    assert resource.recommended_at is None
    assert resource.failure_reason
    markdown = render_briefing(run, [resource], changes, [])
    assert resource.service in section(markdown, "待核实")


@pytest.mark.parametrize(
    "fields",
    [
        ("api_url", "docs_url"),
        ("free_type",),
        ("quota",),
        ("quota_unit",),
        ("refresh_cycle",),
        ("claim_conditions",),
        ("payment_required",),
        ("payment_method_required",),
        ("models",),
        ("rate_limit",),
    ],
)
def test_each_official_key_fact_requires_its_own_evidence(repository, fields):
    policy = remove_evidence(official_policy(), *fields)
    apply(repository, [policy], "missing-" + "-".join(fields))
    (resource,) = repository.list_resources()
    assert resource.status == "pending"
    assert resource.recommended_at is None
    assert resource.failure_reason


def test_limited_policy_without_official_expiry_is_pending_not_expired(repository):
    policy = remove_evidence(
        official_policy(
            free_type="limited", expires_at=BASE_TIME - timedelta(days=1), expiry_notes="未说明"
        ),
        "expires_at",
    )
    apply(repository, [policy], "unconfirmed-expiry")
    (resource,) = repository.list_resources()
    assert resource.status == "pending"
    assert resource.recommended_at is None


@pytest.mark.parametrize("claimed_policy", ["supported", "unsupported"])
def test_china_conclusion_requires_official_region_evidence(repository, claimed_policy):
    policy = remove_evidence(
        official_policy(china_policy=claimed_policy),
        "china_policy",
        "region_restrictions",
    )
    apply(repository, [policy], "unconfirmed-china")
    (resource,) = repository.list_resources()
    assert resource.china_policy == "unknown"
    assert repository.list_resources(china_policy=claimed_policy) == []


def test_official_china_policy_does_not_claim_network_testing(repository):
    policy = official_policy()
    run, changes = apply(repository, [policy], "china-supported", scope=Scope(region="china"))
    (resource,) = repository.list_resources(china_policy="supported")
    assert resource.status == "active"
    assert any(
        item.field in {"china_policy", "region_restrictions"} and item.source_type == "official"
        for item in resource.evidence
    )
    markdown = render_briefing(run, [resource], changes, [])
    assert resource.service in section(markdown, "新发现")
    assert "官方支持中国大陆" in markdown
    assert "网络" in markdown and "未实测" in markdown
    assert "未实测调用" in markdown


def test_china_recheck_scope_includes_unknown_and_unsupported_policies():
    scope = Scope(categories=[Category.TEXT], region="china")
    assert scope.includes(official_policy(china_policy="unknown"))
    assert scope.includes(official_policy(china_policy="unsupported"))
    assert not scope.includes(official_policy(category="image"))


def test_category_scope_preserves_outside_records_even_if_returned_or_not_rechecked(repository):
    text = official_policy()
    image = official_policy(category="image", service="Fixture Image API", service_key="image")
    video = official_policy(category="video", service="Fixture Video API", service_key="video")
    apply(repository, [text, image, video], "all-categories")
    before = {resource.service_key: resource for resource in repository.list_resources()}
    later = BASE_TIME + timedelta(days=1)
    changed_text = revise_policy(text, checked_at=later, quota="2222")
    unsolicited_image = revise_policy(image, checked_at=later, payment_required=True)
    run, changes = apply(
        repository,
        [changed_text, unsolicited_image],
        "text-only",
        now=later,
        scope=Scope(categories=[Category.TEXT]),
    )
    after = {resource.service_key: resource for resource in repository.list_resources()}
    assert after["image"] == before["image"]
    assert after["video"] == before["video"]
    assert after[text.service_key].quota == "2222"
    assert len(changes) == 1
    assert changes[0].resource_id == before[text.service_key].id
    assert run.scope.categories == ["text"]
    assert len(repository.history(before["image"].id)) == 1
    assert len(repository.history(before["video"].id)) == 1


def test_reopening_database_retains_resources_runs_evidence_history_and_same_day_reports(tmp_path):
    data_dir = tmp_path / "database"
    repository = Repository(data_dir)
    policy = official_policy()
    first, changes = apply(repository, [policy], "same-day-first")
    (original,) = repository.list_resources()
    reports_dir = data_dir / "briefings"
    reports_dir.mkdir()
    first_path = reports_dir / f"{first.id}.md"
    first_text = render_briefing(first, [original], changes, [])
    first_path.write_text(first_text, encoding="utf-8")
    first.briefing_path = str(first_path)
    repository.save_run(first)
    later = BASE_TIME + timedelta(hours=1)
    second_policy = revise_policy(policy, checked_at=later, quota="777")
    second, changes = apply(repository, [second_policy], "same-day-second", now=later)
    (current,) = repository.list_resources()
    second_path = reports_dir / f"{second.id}.md"
    second_text = render_briefing(second, [current], changes, [])
    second_path.write_text(second_text, encoding="utf-8")
    second.briefing_path = str(second_path)
    repository.save_run(second)
    old_history = repository.history(current.id)
    del repository

    reopened = Repository(data_dir)
    reopened_resources = reopened.list_resources()
    assert len(reopened_resources) == 1
    assert reopened_resources[0].model_dump(exclude={"messages"}) == current.model_dump(
        exclude={"messages"}
    )
    reopened_current = reopened.get_resource(current.id)
    assert reopened_current is not None
    assert reopened_current.model_dump(exclude={"messages"}) == current.model_dump(
        exclude={"messages"}
    )
    assert reopened.get_resource("missing") is None
    assert reopened.history(current.id) == old_history
    assert len(old_history) == 2
    assert old_history[1].before["quota"] == "1000"
    assert old_history[1].after["quota"] == "777"
    assert old_history[1].evidence == current.evidence
    assert reopened.get_changes(second.id) == changes
    assert reopened.get_run(first.id) == first
    assert reopened.get_run(second.id) == second
    assert {run.id for run in reopened.list_runs()} == {first.id, second.id}
    assert first_path != second_path
    assert first_path.read_text(encoding="utf-8") == first_text
    assert second_path.read_text(encoding="utf-8") == second_text


def test_briefing_separates_formal_recommendations_pending_leads_and_failures(repository):
    formal = official_policy(service="Fixture Official Recommendation")
    pending = official_policy(
        service="Fixture Community Lead", service_key="community", evidence=[]
    )
    run, changes = apply(repository, [formal, pending], "mixed-briefing")
    resources = repository.list_resources()
    markdown = render_briefing(run, resources, changes, ["视频类别尚未完成：来源暂不可达"])
    formal_section = section(markdown, "新发现")
    pending_section = section(markdown, "待核实")
    assert formal.service in formal_section
    assert pending.service not in formal_section
    assert pending.service in pending_section
    assert formal.service not in pending_section
    assert "视频类别尚未完成" in section(markdown, "核查失败")
    assert "未实测调用" in markdown
    assert "未实测" in markdown


def test_empty_increment_briefing_explicitly_reports_no_change(repository):
    run = completed_run("no-findings")
    markdown = render_briefing(run, [], [], [])
    assert "本次无新增或变化" in markdown
    assert run.id in visible(markdown)
    assert "未实测调用" in markdown


def test_limited_relative_validity_is_active_without_inventing_absolute_expiry(repository):
    policy = official_policy(
        free_type="limited",
        expires_at=None,
        expiry_notes="领取后30天有效",
        claim_conditions="免费注册后手动领取；无需付款或绑定支付方式",
    )
    run, changes = apply(repository, [policy], "relative-expiry")
    (original,) = repository.list_resources()
    assert original.status == "active"
    assert original.expires_at is None
    assert original.expiry_notes == "领取后30天有效"
    assert any(item.field == "expiry_notes" for item in original.evidence)
    assert original.service in section(render_briefing(run, [original], changes, []), "新发现")

    later = BASE_TIME + timedelta(days=400)
    rechecked = revise_policy(policy, checked_at=later)
    _, changes = apply(repository, [rechecked], "relative-rechecked", now=later)
    (current,) = repository.list_resources()
    assert current.id == original.id
    assert current.status == "active"
    assert current.expires_at is None
    assert current.recommended_at == original.recommended_at
    assert changes == []
    assert len(repository.history(current.id)) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("quota", "未说明"),
        ("quota_unit", "未核实"),
        ("claim_conditions", "未说明"),
        ("free_type", "unknown"),
    ],
)
def test_unknown_key_conditions_are_not_inferred_free_from_evidence(repository, field, value):
    policy = official_policy(**{field: value})
    apply(repository, [policy], f"unknown-{field}")
    (resource,) = repository.list_resources()
    assert resource.status == "pending"
    assert resource.recommended_at is None


def test_china_briefing_keeps_unclear_official_region_as_separate_lead(repository):
    policy = official_policy(china_policy="unknown", region_restrictions="未说明")
    run, changes = apply(repository, [policy], "china-unclear", scope=Scope(region="china"))
    (resource,) = repository.list_resources()
    assert resource.china_policy == "unknown"
    assert resource.recommended_at is None
    markdown = render_briefing(run, [resource], changes, [])
    assert resource.service not in section(markdown, "新发现")
    assert resource.service in section(markdown, "待核实")


def test_existing_v3_database_upgrades_in_place_and_reopens_as_noop(tmp_path):
    data_dir = tmp_path / "upgrade"
    data_dir.mkdir()
    db_path = data_dir / "radar.sqlite3"
    connection = sqlite3.connect(db_path)
    for script in MIGRATIONS[:3]:
        connection.executescript(script)
    connection.execute("PRAGMA user_version = 3")
    connection.commit()
    connection.close()

    repository = Repository(data_dir)
    with repository._connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)

    reopened = Repository(data_dir)
    with reopened._connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    assert reopened.discoveries_for_run("missing") == []


def test_record_discoveries_skips_replays_and_keeps_other_categories(repository):
    leads = [
        LeadDiscovery(
            url="https://alpha.example/api",
            category=Category.TEXT,
            source_class="discovery-only",
            origin="search",
            provider="Alpha",
            query="free text api",
            discovered_at=BASE_TIME,
        ),
        LeadDiscovery(
            url="https://beta.example/api",
            category=Category.TEXT,
            source_class="official-verifiable",
            origin="direct",
            discovered_at=BASE_TIME,
        ),
    ]
    assert repository.record_discoveries("run-1", leads) == 2
    assert repository.record_discoveries("run-1", leads) == 0
    assert (
        repository.record_discoveries(
            "run-1",
            [
                LeadDiscovery(
                    url="https://alpha.example/api",
                    category=Category.IMAGE,
                    source_class="discovery-only",
                    origin="search",
                )
            ],
        )
        == 1
    )
    assert len(repository.discoveries_for_run("run-1")) == 3


def test_discoveries_round_trip_fields_timezone_and_order(repository):
    earlier = LeadDiscovery(
        url="https://first.example/api",
        category=Category.TEXT,
        source_class="official-verifiable",
        origin="direct",
        provider="First",
        query=None,
        discovered_at=BASE_TIME,
    )
    later = LeadDiscovery(
        url="https://second.example/api",
        category=Category.VIDEO,
        source_class="discovery-only",
        origin="link",
        provider=None,
        query="free video",
        discovered_at=BASE_TIME + timedelta(hours=1),
    )
    repository.record_discoveries("run-order", [later, earlier])

    leads = repository.discoveries_for_run("run-order")
    assert [lead.url for lead in leads] == [
        "https://first.example/api",
        "https://second.example/api",
    ]
    assert leads[0].category == Category.TEXT
    assert leads[0].source_class == "official-verifiable"
    assert leads[0].origin == "direct"
    assert leads[0].provider == "First"
    assert leads[0].query is None
    assert leads[1].category == Category.VIDEO
    assert leads[1].source_class == "discovery-only"
    assert leads[1].origin == "link"
    assert leads[1].provider is None
    assert leads[1].query == "free video"
    assert leads[0].discovered_at.tzinfo is not None
    assert leads[0].discovered_at == BASE_TIME
    assert leads[1].discovered_at == BASE_TIME + timedelta(hours=1)
    assert repository.discoveries_for_run("unknown-run") == []


def test_duplicate_url_within_one_call_inserts_once(repository):
    lead = LeadDiscovery(
        url="https://duplicate.example/api",
        category=Category.TEXT,
        source_class="discovery-only",
        origin="search",
    )
    assert repository.record_discoveries("run-dup", [lead, lead.model_copy()]) == 1
    assert len(repository.discoveries_for_run("run-dup")) == 1
