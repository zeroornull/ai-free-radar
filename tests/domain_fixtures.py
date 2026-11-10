"""Deterministic, explicitly synthetic official-policy records for domain tests only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from aifreeradar.models import Evidence, Policy, Run, Scope

BASE_TIME = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
CATEGORIES = ("text", "image", "video", "speech", "embedding", "rerank")
QUOTA_UNITS = {
    "text": "tokens",
    "image": "images",
    "video": "seconds",
    "speech": "seconds",
    "embedding": "tokens",
    "rerank": "requests",
}


def official_policy(*, checked_at: datetime = BASE_TIME, **overrides: Any) -> Policy:
    """Supply field-specific evidence, including both payment flags and API access.

    The reserved .test domain prevents these fixtures from resembling collected
    production resources. No test fetches or calls these URLs.
    """
    category = overrides.get("category", "text")
    values: dict[str, Any] = {
        "provider": "Fixture Provider",
        "service": "Fixture Text API",
        "category": category,
        "provider_domain": "fixture-provider.test",
        "service_key": "fixture-text-api",
        "aliases": [],
        "models": ["fixture-model-v1"],
        "api_url": "https://fixture-provider.test/api",
        "docs_url": "https://fixture-provider.test/docs/api",
        "free_type": "ongoing",
        "quota": "1000",
        "quota_unit": QUOTA_UNITS[str(category)],
        "refresh_cycle": "每日 00:00 UTC",
        "rate_limit": "10 requests/minute",
        "claim_conditions": "免费注册；无需领取或充值",
        "payment_required": False,
        "payment_method_required": False,
        "expires_at": None,
        "expiry_notes": "持续政策；未指定截止日期",
        "region_restrictions": "支持中国大陆用户注册并使用此 API",
        "china_policy": "supported",
        "status": "active",
        "check_status": "success",
        "failure_reason": "",
    }
    values.update(overrides)
    if values["free_type"] == "limited":
        if "expires_at" not in overrides:
            values["expires_at"] = checked_at + timedelta(days=30)
        if "expiry_notes" not in overrides:
            values["expiry_notes"] = "赠额到期后失效；无需付款或绑定支付方式"
        if "refresh_cycle" not in overrides:
            values["refresh_cycle"] = "一次性赠额，不刷新"
    fields = (
        "api_url",
        "docs_url",
        "free_type",
        "quota",
        "quota_unit",
        "refresh_cycle",
        "rate_limit",
        "claim_conditions",
        "payment_required",
        "payment_method_required",
        "models",
        "expiry_notes",
        "region_restrictions",
        "china_policy",
    )
    if values["expires_at"] is not None:
        fields += ("expires_at",)
    domain = values["provider_domain"]
    evidence = [
        Evidence(
            id=f"{values['service_key']}:{field}:{checked_at.isoformat()}",
            field=field,
            url=f"https://{domain}/policies/{values['service_key']}#{field}",
            quote=f"Fixture official statement for {field}: {values[field]}",
            source_type="official",
            checked_at=checked_at,
            official_domain=domain,
        )
        for field in fields
    ]
    values.setdefault("evidence", evidence)
    return Policy(**values)


def revise_policy(policy: Policy, *, checked_at: datetime, **updates: Any) -> Policy:
    """Refresh policy evidence without accidentally retaining an older field value."""
    values = policy.model_dump(exclude={"evidence"})
    values.update(updates)
    return official_policy(checked_at=checked_at, **values)


def completed_run(
    task_id: str,
    *,
    now: datetime = BASE_TIME,
    scope: Scope | None = None,
    **overrides: Any,
) -> Run:
    values: dict[str, Any] = {
        "id": task_id,
        "scope": scope if scope is not None else Scope(),
        "trigger": "manual",
        "status": "success",
        "started_at": now,
        "finished_at": now,
        "notes": ["测试研究范围完整；未执行候选 API 调用"],
    }
    values.update(overrides)
    return Run(**values)
