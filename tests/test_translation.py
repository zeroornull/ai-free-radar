"""Deterministic coverage of the additive Simplified-Chinese translation engine."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from aifreeradar.config import Settings
from aifreeradar.models import (
    UNKNOWN,
    CollectedMessage,
    Evidence,
    MessageSource,
    NewsItem,
    Policy,
    Resource,
)
from aifreeradar.translation import (
    MESSAGE_TRANSLATED_FIELDS,
    POLICY_TRANSLATED_FIELDS,
    ModelTranslator,
    needs_translation,
    translate_message,
    translate_resource_failure,
)

CHECKED = datetime(2026, 11, 1, 1, tzinfo=UTC)

# Fixed zh answers keyed by the batch key the engine sends; every answer holds
# CJK. Originals are never part of this mapping, so an unexpected key fails loudly.
ZH = {
    "title": "免费文本接口层级发布",
    "summary": "免费接口层级，每月一千次请求，无需购买",
    "end_reason": "官方公告：活动已结束",
    "policy.quota": "每月一千次请求",
    "policy.quota_unit": "请求次数",
    "policy.refresh_cycle": "每月刷新",
    "policy.rate_limit": "每分钟十次请求",
    "policy.claim_conditions": "免费注册且无需购买",
    "policy.expiry_notes": "无固定截止日期",
    "policy.region_restrictions": "全球可用",
    "failure_reason": "核验期间官方定价页无法访问",
}
EXPECTED_BATCH = {
    *MESSAGE_TRANSLATED_FIELDS,
    *(f"policy.{field}" for field in POLICY_TRANSLATED_FIELDS),
}


def english_policy(**updates) -> Policy:
    values = {
        "provider": "Example Provider",
        "service": "Free Text API",
        "category": "text",
        "provider_domain": "example.com",
        "service_key": "free-text-api",
        "api_url": "https://example.com/api",
        "docs_url": "https://example.com/docs",
        "free_type": "ongoing",
        "quota": "1000 requests per month",
        "quota_unit": "requests",
        "refresh_cycle": "monthly",
        "rate_limit": "10 requests per minute",
        "claim_conditions": "Free registration and no purchase required",
        "payment_required": False,
        "payment_method_required": False,
        "expiry_notes": "No fixed end date",
        "region_restrictions": "Available worldwide",
        "china_policy": "unknown",
        "status": "pending",
        "failure_reason": "Official pricing page unreachable during verification",
        "evidence": [
            Evidence(
                field="quota",
                url="https://example.com/policy",
                quote="Official quota statement: 1000 requests per month",
                source_type="official",
                checked_at=CHECKED,
            )
        ],
    }
    values.update(updates)
    return Policy(**values)


def english_message(**updates) -> CollectedMessage:
    values = {
        "policy": english_policy(),
        "title": "Free Text API tier announced",
        "summary": "Free API tier with 1000 monthly requests and no purchase required",
        "sources": [
            MessageSource(
                url="https://example.com/free-api",
                title="Free Text API official page",
                excerpt="Free tier with 1000 requests per month and no purchase required.",
                source_type="official",
                access="page",
            )
        ],
        "ended": True,
        "end_reason": "Official announcement says the campaign has ended",
    }
    values.update(updates)
    return CollectedMessage(**values)


class FixedTranslator:
    """Stub Translator that answers fixed zh and records every batch it receives."""

    def __init__(self, answers: dict[str, str] | None = None) -> None:
        self.answers = dict(ZH if answers is None else answers)
        self.batches: list[dict[str, str]] = []

    async def translate(self, texts: dict[str, str]) -> dict[str, str]:
        self.batches.append(dict(texts))
        return {key: self.answers[key] for key in texts if key in self.answers}


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \t\n",
        UNKNOWN,
        f"  {UNKNOWN}  ",
        "免费额度每月一千次，无需购买。",
        "1000",
        "1,000.50 — 100%",
        "!!! ??? ...",
        "中文中文中文 ab",  # 6 CJK / 2 letters
        "免免免 abcdefghij",  # exactly 0.3 is not below the threshold
    ],
)
def test_needs_translation_skips_placeholders_chinese_and_symbols(text):
    assert needs_translation(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "Free tier with 1000 requests per month",
        "monthly",
        "10 requests per minute",
        "免 abcd",  # 1 CJK / 4 letters = 0.25
    ],
)
def test_needs_translation_flags_english_and_low_cjk_ratio(text):
    assert needs_translation(text) is True


@pytest.mark.asyncio
async def test_translate_message_populates_only_zh_and_preserves_originals():
    message = english_message()
    translator = FixedTranslator()

    result = await translate_message(translator, message)

    assert result is not message
    assert isinstance(result, CollectedMessage)
    assert not isinstance(result, NewsItem)
    assert (result.title_zh, result.summary_zh, result.end_reason_zh) == (
        ZH["title"],
        ZH["summary"],
        ZH["end_reason"],
    )
    for field in POLICY_TRANSLATED_FIELDS:
        assert getattr(result.policy, f"{field}_zh") == ZH[f"policy.{field}"]

    # Originals, brand names, evidence and sources stay authoritative.
    assert (result.title, result.summary, result.end_reason) == (
        message.title,
        message.summary,
        message.end_reason,
    )
    assert (result.policy.provider, result.policy.service) == ("Example Provider", "Free Text API")
    for field in POLICY_TRANSLATED_FIELDS:
        assert getattr(result.policy, field) == getattr(message.policy, field)
    assert result.policy.evidence == message.policy.evidence
    assert result.sources == message.sources
    assert result.policy.failure_reason == message.policy.failure_reason
    assert result.policy.failure_reason_zh == ""

    # The in-memory original is never mutated.
    assert (message.title_zh, message.summary_zh, message.end_reason_zh) == ("", "", "")
    assert all(getattr(message.policy, f"{field}_zh") == "" for field in POLICY_TRANSLATED_FIELDS)

    (batch,) = translator.batches
    assert set(batch) == EXPECTED_BATCH
    assert batch["title"] == message.title
    assert batch["policy.quota"] == "1000 requests per month"
    assert "failure_reason" not in batch


@pytest.mark.asyncio
async def test_translate_message_skips_chinese_placeholders_and_untranslated_fields():
    message = english_message(
        title="免费接口发布",
        summary=UNKNOWN,
        end_reason="",
        ended=False,
        policy=english_policy(
            quota=UNKNOWN,
            quota_unit="次",
            refresh_cycle="每日 00:00 UTC",
            claim_conditions="免费注册",
            expiry_notes="持续政策",
            region_restrictions="支持中国大陆用户注册",
        ),
    )
    translator = FixedTranslator()

    result = await translate_message(translator, message)

    assert translator.batches == [{"policy.rate_limit": "10 requests per minute"}]
    assert result.policy.rate_limit_zh == ZH["policy.rate_limit"]
    assert (result.title_zh, result.summary_zh, result.end_reason_zh) == ("", "", "")
    for field in POLICY_TRANSLATED_FIELDS:
        if field != "rate_limit":
            assert getattr(result.policy, f"{field}_zh") == ""
    assert message.policy.rate_limit_zh == ""


@pytest.mark.asyncio
async def test_translate_message_returns_the_same_object_when_nothing_needs_zh():
    message = english_message(
        title="免费接口发布",
        summary="每月一千次免费请求，无需购买",
        end_reason="官方公告：活动已结束",
        policy=english_policy(
            quota="每月一千次请求",
            quota_unit="次",
            refresh_cycle="每月",
            rate_limit="每分钟十次请求",
            claim_conditions="免费注册",
            expiry_notes="无截止日期",
            region_restrictions="全球可用",
        ),
    )
    translator = FixedTranslator()

    assert await translate_message(translator, message) is message
    assert translator.batches == []


@pytest.mark.asyncio
async def test_translate_message_preserves_the_news_item_subtype():
    message = english_message()
    news = NewsItem(
        **message.model_dump(),
        resource_id="resource-1",
        task_id="task-1",
        kind="new",
        discovered_at=CHECKED,
        first_seen_at=CHECKED,
    )

    result = await translate_message(FixedTranslator(), news)

    assert isinstance(result, NewsItem)
    assert (result.id, result.resource_id, result.task_id, result.kind) == (
        news.id,
        "resource-1",
        "task-1",
        "new",
    )
    assert (result.discovered_at, result.first_seen_at) == (CHECKED, CHECKED)
    assert result.title_zh == ZH["title"]
    assert news.title_zh == ""


@pytest.mark.asyncio
async def test_translate_resource_failure_populates_only_failure_reason_zh():
    resource = Resource(**english_policy().model_dump())
    translator = FixedTranslator()

    result = await translate_resource_failure(translator, resource)

    assert result is not resource
    assert result.failure_reason_zh == ZH["failure_reason"]
    assert result.failure_reason == resource.failure_reason
    assert translator.batches == [{"failure_reason": resource.failure_reason}]
    for field in POLICY_TRANSLATED_FIELDS:
        assert getattr(result, f"{field}_zh") == ""
    assert result.quota == "1000 requests per month"
    assert result.evidence == resource.evidence
    assert resource.failure_reason_zh == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["", UNKNOWN, "   ", "官方页面无法访问"])
async def test_translate_resource_failure_skips_non_english_reasons(reason):
    resource = Resource(**english_policy(failure_reason=reason).model_dump())
    translator = FixedTranslator()

    assert await translate_resource_failure(translator, resource) is resource
    assert translator.batches == []


def prompt_text(messages) -> str:
    return "\n".join(
        str(getattr(part, "content", part))
        for message in messages
        for part in getattr(message, "parts", ())
    )


def counting_model(calls, answers=None, *, fail=False, echo=False):
    """Deterministic injected model; records each prompt and answers fixed zh."""

    def respond(messages, info):
        text = prompt_text(messages)
        calls.append(text)
        if fail:
            raise RuntimeError("model unavailable")
        payload = json.loads(text.strip().splitlines()[-1])
        if echo:
            translations = dict(payload)
        elif answers is not None:
            translations = {
                key: answers[value] for key, value in payload.items() if value in answers
            }
        else:
            translations = {key: f"中文译文：{value}" for key, value in payload.items()}
        return ModelResponse(
            [ToolCallPart(info.output_tools[0].name, {"translations": translations})]
        )

    return FunctionModel(respond)


@pytest.mark.asyncio
async def test_model_translator_caches_by_original_text(tmp_path):
    settings = Settings(data_dir=tmp_path, schedule_enabled=False)
    calls: list[str] = []
    translator = ModelTranslator(settings, model=counting_model(calls))
    texts = {"title": "Free tier", "summary": "Monthly free requests"}

    first = await translator.translate(texts)
    assert first == {"title": "中文译文：Free tier", "summary": "中文译文：Monthly free requests"}
    assert len(calls) == 1

    assert await translator.translate(dict(texts)) == first
    assert len(calls) == 1, "unchanged originals must never reach the model again"

    cache = tmp_path / "translation_cache.json"
    assert cache.is_file()
    stored = json.loads(cache.read_text(encoding="utf-8"))
    assert set(stored) == {
        hashlib.sha256(value.encode("utf-8")).hexdigest() + ":zh" for value in texts.values()
    }

    reloaded_calls: list[str] = []
    reloaded = ModelTranslator(settings, model=counting_model(reloaded_calls))
    assert await reloaded.translate(dict(texts)) == first
    assert reloaded_calls == []

    changed = await translator.translate({"title": "Free tier with a bonus"})
    assert changed == {"title": "中文译文：Free tier with a bonus"}
    assert len(calls) == 2

    assert await translator.translate({"quota": UNKNOWN, "note": "免费"}) == {}
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["model_error", "empty_answer", "non_cjk_echo"])
async def test_model_translator_failures_leave_zh_empty_and_never_raise(tmp_path, mode):
    settings = Settings(data_dir=tmp_path, schedule_enabled=False)
    calls: list[str] = []
    if mode == "model_error":
        model = counting_model(calls, fail=True)
    elif mode == "empty_answer":
        model = counting_model(calls, answers={})
    else:
        model = counting_model(calls, echo=True)
    translator = ModelTranslator(settings, model=model)

    assert await translator.translate({"title": "Free tier"}) == {}
    assert calls
    assert not (tmp_path / "translation_cache.json").exists()

    message = english_message()
    assert await translate_message(translator, message) is message
    assert message.title_zh == ""
    resource = Resource(**english_policy().model_dump())
    assert await translate_resource_failure(translator, resource) is resource
    assert resource.failure_reason_zh == ""


@pytest.mark.asyncio
async def test_model_translator_trims_answers_and_requires_cjk(tmp_path):
    settings = Settings(data_dir=tmp_path, schedule_enabled=False)
    calls: list[str] = []
    answers = {"Free tier": "  免费层级  ", "Free bonus": "free bonus"}
    translator = ModelTranslator(settings, model=counting_model(calls, answers=answers))

    result = await translator.translate({"title": "Free tier", "summary": "Free bonus"})

    assert result == {"title": "免费层级"}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_model_translator_splits_batches(tmp_path):
    settings = Settings(data_dir=tmp_path, schedule_enabled=False)
    calls: list[str] = []
    translator = ModelTranslator(settings, model=counting_model(calls))
    texts = {f"field-{index}": f"Free offer number {index}" for index in range(25)}

    result = await translator.translate(texts)

    assert len(calls) == 2
    assert set(result) == set(texts)
    assert all(value.startswith("中文译文：") for value in result.values())