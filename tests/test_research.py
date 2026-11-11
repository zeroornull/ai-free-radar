"""Research boundary tests: external transports only are replaced; Harness stays real."""

from __future__ import annotations

import asyncio
import http.client
import ipaddress
import json
import socket
from datetime import UTC, datetime
from email.message import Message
from typing import Literal, cast

import httpx
import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.test import TestModel

from aifreeradar.config import ConfigurationError, Settings, load_settings
from aifreeradar.models import (
    Category,
    CollectedMessage,
    Evidence,
    MessageSource,
    Policy,
    ResearchBatch,
    Resource,
    RunStats,
    Scope,
)
from aifreeradar.research import (
    BASELINE_QUERIES,
    COLLECTION_INSTRUCTIONS,
    COLLECTION_PAGE_LIMIT,
    MAX_BATCH_FETCH,
    MAX_COLLECTION_FETCH,
    MAX_COLLECTION_SEARCH,
    MAX_DIRECT_FETCH,
    MAX_VERIFY_FETCH,
    MAX_VERIFY_SEARCH,
    MODEL_PAGE_LIMIT,
    RECHECK_GROUP_SIZE,
    FetchedPage,
    HarnessResearcher,
    MemoryWorkspace,
    PublicPageFetcher,
    ResearchContext,
    ResearchError,
    SearchClient,
    clip_for_model,
)


@pytest.mark.parametrize(
    ("model", "variable"),
    [
        ("openai:gpt-4.1-mini", "TEST_OPENAI_KEY"),
        ("openai-chat:gpt-4.1-mini", "TEST_OPENAI_KEY"),
        ("anthropic:claude-sonnet-4-5", "TEST_CLAUDE_KEY"),
        ("deepseek:deepseek-chat", "TEST_DEEPSEEK_KEY"),
    ],
)
def test_selected_model_requires_its_own_credential(tmp_path, monkeypatch, model, variable):
    monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-key-must-not-be-used")
    settings = Settings(data_dir=tmp_path, model=model, model_api_key_env=variable)
    with pytest.raises(ConfigurationError, match=variable):
        settings.model_credential()
    monkeypatch.setenv(variable, " selected-key ")
    assert settings.model_credential() == "selected-key"


@pytest.mark.parametrize("provider", ["tavily", "brave", "exa"])
def test_selected_search_requires_explicit_credential(tmp_path, monkeypatch, provider):
    monkeypatch.delenv("TEST_SEARCH_KEY", raising=False)
    settings = Settings(
        data_dir=tmp_path,
        search_provider=provider,
        search_api_key_env="TEST_SEARCH_KEY",
    )
    with pytest.raises(ConfigurationError, match=provider):
        settings.search_credential()
    monkeypatch.setenv("TEST_SEARCH_KEY", "selected-search-key")
    assert settings.search_credential() == "selected-search-key"


def test_duckduckgo_is_explicit_and_needs_no_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_SEARCH_KEY", raising=False)
    settings = Settings(
        data_dir=tmp_path,
        search_provider="duckduckgo",
        search_api_key_env="TEST_SEARCH_KEY",
    )
    assert settings.search_credential() is None
    with pytest.raises(ValidationError):
        Settings(data_dir=tmp_path, search_provider=cast(Literal["duckduckgo", "tavily", "brave", "exa"], "automatic"))
    with pytest.raises(ValidationError):
        Settings(data_dir=tmp_path, model="unsupported:some-model")


def test_compatible_model_uses_named_endpoint_not_openai(tmp_path, monkeypatch):
    with pytest.raises(ValidationError, match="model_base_url"):
        Settings(data_dir=tmp_path, model="grok/grok-4.7-build-fast@500k", model_api_key_env="XAI_API_KEY")
    with pytest.raises(ValidationError, match="model_base_url"):
        Settings(data_dir=tmp_path, model="xai:grok-4.7", model_api_key_env="XAI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-must-not-be-sent")
    monkeypatch.setenv("XAI_API_KEY", "xai-selected-key")
    bare = Settings(
        data_dir=tmp_path,
        model="grok/grok-4.7-build-fast@500k",
        model_base_url="http://127.0.0.1:3425/v1",
        model_api_key_env="XAI_API_KEY",
    )
    bare_model = HarnessResearcher(bare)._model()
    assert isinstance(bare_model, OpenAIChatModel)
    assert bare_model.model_name == "grok/grok-4.7-build-fast@500k"
    assert bare_model.system == "127.0.0.1"
    assert str(bare_model.base_url).rstrip("/") == "http://127.0.0.1:3425/v1"
    assert bare_model.client.api_key == "xai-selected-key"
    prefixed = Settings(
        data_dir=tmp_path,
        model="compatible:grok-4.7",
        model_base_url="https://api.x.ai/v1",
        model_api_key_env="XAI_API_KEY",
    )
    model = HarnessResearcher(prefixed)._model()
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "grok-4.7"
    assert model.system == "api.x.ai"
    assert str(model.base_url).rstrip("/") == "https://api.x.ai/v1"
    assert model.client.api_key == "xai-selected-key"


def test_config_file_key_is_used_instead_of_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key-must-not-be-used")
    monkeypatch.setenv("EXA_API_KEY", "env-search-must-not-be-used")
    settings = Settings(
        data_dir=tmp_path,
        model_api_key="file-model-key",
        search_provider="exa",
        search_api_key="file-search-key",
    )
    assert settings.model_credential() == "file-model-key"
    assert settings.search_credential() == "file-search-key"
    assert "file-model-key" not in settings.public_summary().values()


@pytest.mark.asyncio
async def test_exa_search_calls_only_exa(tmp_path, monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa-secret")
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Docs",
                        "url": "https://example.com/policy",
                        "highlights": ["free quota", "no card"],
                    },
                    {"title": "Missing URL"},
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("aifreeradar.research.httpx.AsyncClient", factory)
    settings = Settings(
        data_dir=tmp_path, search_provider="exa", search_api_key_env="EXA_API_KEY"
    )
    results = await SearchClient(settings).search("free api policy")
    assert seen["url"] == "https://api.exa.ai/search"
    assert seen["key"] == "exa-secret"
    assert seen["body"] == {
        "query": "free api policy",
        "type": "auto",
        "numResults": 8,
        "contents": {"highlights": True},
    }
    assert results == [
        {
            "title": "Docs",
            "url": "https://example.com/policy",
            "snippet": "free quota no card",
        }
    ]


def test_config_and_dotenv_resolve_relative_to_config_file(tmp_path, monkeypatch):
    config_dir = tmp_path / "configuration"
    config_dir.mkdir()
    config = config_dir / "radar.toml"
    config.write_text(
        'data_dir = "../records"\n'
        'model = "deepseek:deepseek-chat"\n'
        'model_api_key_env = "RADAR_TEST_KEY"\n'
        'model_base_url = "https://api.deepseek.com"\n'
        'search_provider = "brave"\n'
        'search_api_key_env = "RADAR_SEARCH_KEY"\n'
        'schedule_time = "18:25"\n'
        '[default_scope]\ncategories = ["embedding", "rerank"]\nregion = "china"\n',
        encoding="utf-8",
    )
    (config_dir / ".env").write_text(
        "RADAR_TEST_KEY=dotenv-model-key\nRADAR_SEARCH_KEY=dotenv-search-key\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("RADAR_TEST_KEY", raising=False)
    monkeypatch.delenv("RADAR_SEARCH_KEY", raising=False)
    monkeypatch.setenv("AIFREERADAR_CONFIG", str(config))
    # load_dotenv writes into os.environ; register both variables for fixture cleanup.
    monkeypatch.setenv("RADAR_TEST_KEY", "")
    monkeypatch.delenv("RADAR_TEST_KEY")
    monkeypatch.setenv("RADAR_SEARCH_KEY", "")
    monkeypatch.delenv("RADAR_SEARCH_KEY")
    settings = load_settings()
    assert settings.data_dir == (tmp_path / "records").resolve()
    assert settings.model_credential() == "dotenv-model-key"
    assert settings.search_credential() == "dotenv-search-key"
    assert settings.model == "deepseek:deepseek-chat"
    assert settings.model_base_url == "https://api.deepseek.com"
    assert settings.default_scope.categories == ["embedding", "rerank"]
    assert settings.default_scope.region == "china"
    assert settings.schedule_time == "18:25"


def test_missing_explicit_config_and_nonloopback_host_are_errors(tmp_path):
    with pytest.raises(ConfigurationError, match="Configuration file not found"):
        load_settings(tmp_path / "missing.toml")
    with pytest.raises(ValidationError):
        Settings(data_dir=tmp_path, host=cast(Literal["127.0.0.1"], "0.0.0.0"))
    with pytest.raises(ValidationError):
        Settings(data_dir=tmp_path, schedule_time="25:00")


def test_existing_environment_overrides_dotenv_without_public_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("RADAR_TEST_KEY", "existing-secret")
    (tmp_path / ".env").write_text("RADAR_TEST_KEY=file-secret\n", encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text('model_api_key_env = "RADAR_TEST_KEY"\n', encoding="utf-8")
    settings = load_settings(config)
    assert settings.model_credential() == "existing-secret"
    summary = str(settings.public_summary())
    assert "existing-secret" not in summary
    assert "file-secret" not in summary
    assert "RADAR_TEST_KEY" not in summary


CHECKED = datetime(2026, 11, 10, 6, tzinfo=UTC)
SOURCE = "https://docs.example.test/free-api"
QUOTE = (
    "Developer API free tier provides 1000 requests per month. "
    "No payment required. No credit card required. Free registration. "
    "API documentation describes the Developer API."
)
COMMUNITY = "https://community.example.org/free-api-report"
SNIPPET = "Example Developer API free tier provides 1000 requests per month. No payment required."
COMMUNITY_SNIPPET = "Community report: Developer API plan offers 1000 free requests per month."
WEB_ONLY_TEXT = "Free image generator website includes 100 credits; no API is provided."


def quoted_policy(**updates):
    values = {
        "provider": "Example",
        "service": "Developer API",
        "category": "text",
        "provider_domain": "example.test",
        "service_key": "developer-api",
        "docs_url": SOURCE,
        "free_type": "ongoing",
        "quota": "1000",
        "quota_unit": "requests",
        "refresh_cycle": "per month",
        "claim_conditions": "Free registration",
        "payment_required": False,
        "payment_method_required": False,
        "status": "active",
        "evidence": [
            Evidence(
                field=field,
                url=SOURCE,
                quote=QUOTE,
                source_type="official",
                checked_at=datetime(2020, 1, 1, tzinfo=UTC),
            )
            for field in (
                "docs_url",
                "free_type",
                "quota",
                "quota_unit",
                "refresh_cycle",
                "claim_conditions",
                "payment_required",
                "payment_method_required",
            )
        ],
    }
    values.update(updates)
    return Policy(**values)


def reported_policy(**updates):
    values = {
        "provider": "Example",
        "service": "Developer API",
        "category": "text",
        "provider_domain": "example.test",
        "service_key": "developer-api",
        "docs_url": SOURCE,
        "free_type": "ongoing",
        "quota": "1000",
        "quota_unit": "requests",
        "refresh_cycle": "per month",
        "claim_conditions": "Free registration",
        "payment_required": False,
        "payment_method_required": False,
    }
    values.update(updates)
    return Policy(**values)


def collected_message(policy=None, sources=None, **updates):
    values = {
        "policy": policy or reported_policy(),
        "offer_key": "developer-free",
        "title": "Free Developer API",
        "summary": "Free 1000 requests per month through the Developer API.",
        "sources": sources
        or [
            MessageSource(
                url=SOURCE,
                title="Free API policy",
                excerpt=QUOTE,
                source_type="official",
                access="page",
            )
        ],
    }
    values.update(updates)
    return CollectedMessage(**values)


def explicit_scope(resource: Resource) -> Scope:
    return Scope(categories=[Category.TEXT], resource_ids=[resource.id])


class SearchTransport:
    """Replace the external search boundary, retaining actual tools and Agent loop."""

    def __init__(self, rows=None, error=None):
        self.calls = []
        self.error = error
        self.rows = rows

    async def search(self, query):
        self.calls.append(query)
        if self.error:
            raise self.error
        return self.rows or [
            {"title": "Example free API", "url": SOURCE, "snippet": SNIPPET}
        ]


class SourceTransport:
    def __init__(self, text=QUOTE, error=None, final_url=SOURCE):
        self.text, self.error, self.final_url = text, error, final_url
        self.calls = []

    async def fetch(self, url):
        self.calls.append(url)
        if self.error:
            raise self.error
        return FetchedPage(self.final_url, self.text, CHECKED)


def tool_results(messages):
    return [
        part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)
    ]


def policy_model(policy=None, *, fail_image=False, empty_recheck=False):
    """Use the supported deterministic model API with real tool execution."""
    policy = policy or quoted_policy()

    def respond(messages, info):
        prompt = "\n".join(
            str(getattr(part, "content", part))
            for message in messages
            for part in getattr(message, "parts", ())
        )
        if fail_image and "image API" in prompt:
            raise RuntimeError("Selected model failed for image research")
        results = tool_results(messages)
        if empty_recheck and "Recheck exactly" in prompt:
            output = ResearchBatch()
        elif not any(part.tool_name == "search_web" for part in results):
            return ModelResponse([ToolCallPart("search_web", {"query": "official free API"})])
        elif not any(part.tool_name == "fetch_page" for part in results):
            return ModelResponse([ToolCallPart("fetch_page", {"url": SOURCE})])
        else:
            output = ResearchBatch(resources=[policy])
        return ModelResponse(
            [
                ToolCallPart(
                    info.output_tools[0].name,
                    output.model_dump(mode="json"),
                )
            ]
        )

    return FunctionModel(respond)


def prompt_text(messages):
    return "\n".join(
        str(getattr(part, "content", part))
        for message in messages
        for part in getattr(message, "parts", ())
    )


def collection_model(message, *, fetch=True, search=False, fail_image=False, prompts=None):
    """Deterministic collection model that executes real tools, then reports messages."""
    fetch_url = message.sources[0].url

    def respond(messages, info):
        text = prompt_text(messages)
        if prompts is not None:
            prompts.append(text)
        if fail_image and "image API" in text:
            raise RuntimeError("Selected model failed for image collection")
        results = tool_results(messages)
        if search and not any(part.tool_name == "search_web" for part in results):
            return ModelResponse([ToolCallPart("search_web", {"query": "official free API"})])
        if fetch and not any(part.tool_name == "fetch_page" for part in results):
            return ModelResponse([ToolCallPart("fetch_page", {"url": fetch_url})])
        return ModelResponse(
            [
                ToolCallPart(
                    info.output_tools[0].name,
                    ResearchBatch(messages=[message]).model_dump(mode="json"),
                )
            ]
        )

    return FunctionModel(respond)


@pytest.mark.asyncio
async def test_default_collection_uses_fetched_page_without_rechecks(tmp_path):
    prompts = []
    message = collected_message()
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=collection_model(message, prompts=prompts),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )
    batch = await researcher.research(Scope(categories=[Category.TEXT]), [])
    assert not batch.resources
    assert not batch.failures
    assert len(batch.messages) == 1
    reported = batch.messages[0]
    assert reported.sources[0].access == "page"
    assert reported.sources[0].source_type == "official"
    assert reported.sources[0].excerpt == QUOTE
    assert reported.policy.status == "pending"
    assert any("EXISTING_OFFERS_JSON" in prompt for prompt in prompts)
    assert not any("Recheck exactly" in prompt for prompt in prompts)


@pytest.mark.asyncio
async def test_research_records_search_fetch_and_model_usage(tmp_path):
    search, fetch = SearchTransport(), SourceTransport()
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=collection_model(collected_message()),
        search_client=cast(SearchClient, search),
        fetcher=cast(PublicPageFetcher, fetch),
    )
    await researcher.research(Scope(categories=[Category.TEXT]), [])
    stats = researcher.last_stats
    assert stats.search_calls == len(search.calls) == 6
    assert stats.fetch_calls == 1
    assert stats.model_requests >= 1
    for value in (
        stats.search_calls,
        stats.fetch_calls,
        stats.model_requests,
        stats.input_tokens,
        stats.output_tokens,
        stats.cache_read_tokens,
        stats.reasoning_tokens,
    ):
        assert isinstance(value, int) and value >= 0



@pytest.mark.asyncio
@pytest.mark.parametrize(
    "defect", ["hallucinated_quote", "unfetched", "wrong_value", "third_party"]
)
async def test_real_agent_rejects_unproven_official_evidence(tmp_path, defect):
    known = Resource(**quoted_policy().model_dump(), id="known-text")
    policy = quoted_policy(resource_id=known.id)
    fetch = SourceTransport()
    if defect == "hallucinated_quote":
        fetch.text = "Official documentation, with no free policy stated."
    elif defect == "unfetched":
        policy.evidence = [
            e.model_copy(update={"url": "https://example.test/never-read"}) for e in policy.evidence
        ]
    elif defect == "wrong_value":
        policy.quota = "9999999"
    else:
        fetch.final_url = "https://community.test/free-api-summary"
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=policy_model(policy),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, fetch),
    )
    batch = await researcher.research(explicit_scope(known), [known])
    assert batch.failures
    assert batch.resources[0].status == "pending"
    assert batch.resources[0].check_status == "failed"
    if defect != "wrong_value":
        assert not batch.resources[0].evidence


@pytest.mark.asyncio
async def test_documentation_link_must_itself_be_fetched(tmp_path):
    known = Resource(**quoted_policy().model_dump(), id="known-text")
    policy = quoted_policy(
        resource_id=known.id, docs_url="https://docs.example.test/not-opened"
    )
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=policy_model(policy),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )
    batch = await researcher.research(explicit_scope(known), [known])
    assert batch.resources[0].status == "pending"
    assert any("documentation link" in failure for failure in batch.failures)


@pytest.mark.asyncio
async def test_limited_offer_preserves_source_validity_without_invented_date(tmp_path):
    quote = (
        "Image API trial provides 20 images valid for 30 days after free registration. "
        "No payment required. No credit card required. "
        "API documentation describes the Image API."
    )
    notes = "valid for 30 days after free registration"
    fields = (
        "docs_url", "free_type", "quota", "quota_unit", "claim_conditions",
        "payment_required", "payment_method_required", "expiry_notes",
    )
    known = Resource(**quoted_policy().model_dump(), id="known-image")
    policy = quoted_policy(
        resource_id=known.id,
        free_type="limited",
        quota="20",
        quota_unit="images",
        expiry_notes=notes,
        expires_at=None,
        evidence=[
            Evidence(
                field=field, url=SOURCE, quote=quote, source_type="official", checked_at=CHECKED,
            )
            for field in fields
        ],
    )
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=policy_model(policy),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport(text=quote)),
    )
    resource, = (await researcher.research(explicit_scope(known), [known])).resources
    assert resource.status == "active"
    assert resource.free_type == "limited"
    assert resource.expires_at is None
    assert resource.expiry_notes == notes
    assert resource.quota_unit == "images"


def test_mainland_support_requires_registration_and_api_use_in_fetched_text(tmp_path):
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=TestModel(call_tools=[], custom_output_args={}),
    )
    weak_url = "https://example.test/regions"
    weak = "China is supported for the website."
    weak_policy = quoted_policy(
        status="pending",
        china_policy="supported",
        evidence=[Evidence(
            field="china_policy", url=weak_url, quote=weak,
            source_type="official", checked_at=CHECKED,
        )],
    )
    checked, errors = researcher.validate_policy(
        weak_policy, ResearchContext(pages={weak_url: FetchedPage(weak_url, weak, CHECKED)}),
    )
    assert checked.china_policy == "unknown"
    assert any("mainland China" in error for error in errors)

    strong_url = "https://example.test/china-api"
    strong = "Mainland China users can register an account and the API is available."
    strong_policy = weak_policy.model_copy(update={
        "evidence": [Evidence(
            field="china_policy", url=strong_url, quote=strong,
            source_type="official", checked_at=CHECKED,
        )],
    })
    checked, errors = researcher.validate_policy(
        strong_policy,
        ResearchContext(pages={strong_url: FetchedPage(strong_url, strong, CHECKED)}),
    )
    assert checked.china_policy == "supported"
    assert not any("mainland China" in error for error in errors)


@pytest.mark.asyncio
async def test_strict_fetch_failure_never_creates_verified_policy(tmp_path):
    known = Resource(**quoted_policy().model_dump(), id="known-text")
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=policy_model(quoted_policy(resource_id=known.id)),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport(error=TimeoutError("unreachable"))),
    )
    batch = await researcher.research(explicit_scope(known), [known])
    assert batch.resources[0].status == "pending"
    assert batch.resources[0].check_status == "failed"
    assert any("Source retrieval failed" in failure for failure in batch.failures)


@pytest.mark.asyncio
async def test_failed_category_preserves_other_real_collection_result(tmp_path):
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=collection_model(collected_message(), fail_image=True),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )
    batch = await researcher.research(Scope(categories=[Category.TEXT, Category.IMAGE]), [])
    assert len(batch.messages) == 1
    assert batch.messages[0].sources[0].access == "page"
    assert any("image" in failure and "failed" in failure for failure in batch.failures)


@pytest.mark.asyncio
async def test_missing_matching_recheck_is_explicit_and_scoped(tmp_path):
    known = Resource(**quoted_policy().model_dump(), id="known-text")
    outside = Resource(**quoted_policy(category="image").model_dump(), id="outside-image")
    expired = Resource(
        **quoted_policy(status="expired", service_key="old-api").model_dump(), id="old-text"
    )
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=policy_model(empty_recheck=True),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )
    batch = await researcher.research(scope=explicit_scope(known), existing=[known, outside, expired])
    assert len(batch.resources) == 1
    attempt = batch.resources[0]
    assert attempt.resource_id == known.id
    assert attempt.check_status == "failed"
    assert attempt.status == known.status and attempt.quota == known.quota
    assert "matching recheck" in attempt.failure_reason
    assert not batch.messages


@pytest.mark.asyncio
async def test_existing_recheck_uses_authoritative_resource_id(tmp_path):
    known = Resource(**quoted_policy().model_dump(), id="known-resource")
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=policy_model(quoted_policy(resource_id="invented-id")),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )
    batch = await researcher.research(explicit_scope(known), [known])
    assert not batch.failures
    assert len(batch.resources) == 1
    assert batch.resources[0].resource_id == known.id


@pytest.mark.asyncio
async def test_missing_model_key_fails_before_external_research(tmp_path, monkeypatch):
    monkeypatch.delenv("ABSENT_MODEL_KEY", raising=False)
    search = SearchTransport()
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path, model_api_key_env="ABSENT_MODEL_KEY"),
        search_client=cast(SearchClient, search),
    )
    with pytest.raises(ConfigurationError, match="ABSENT_MODEL_KEY"):
        await researcher.research(Scope(categories=[Category.TEXT]), [])
    assert not search.calls


@pytest.mark.asyncio
async def test_missing_selected_search_key_fails_with_real_testmodel(tmp_path, monkeypatch):
    monkeypatch.delenv("ABSENT_SEARCH_KEY", raising=False)
    researcher = HarnessResearcher(
        Settings(
            data_dir=tmp_path, search_provider="tavily", search_api_key_env="ABSENT_SEARCH_KEY"
        ),
        model=TestModel(call_tools=[], custom_output_args=ResearchBatch().model_dump(mode="json")),
    )
    with pytest.raises(ConfigurationError, match="tavily"):
        await researcher.research(Scope(categories=[Category.TEXT]), [])


@pytest.mark.asyncio
async def test_configured_search_failure_is_reported_by_real_tool_loop(tmp_path):
    search = SearchTransport(error=RuntimeError("configured provider unavailable"))
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path, search_provider="brave"),
        model=collection_model(collected_message(), fetch=False),
        search_client=cast(SearchClient, search),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )
    batch = await researcher.research(Scope(categories=[Category.TEXT]), [])
    assert search.calls  # baseline prepass and the agent tool share the one configured client
    assert any(
        "brave search failed" in failure and "no fallback" in failure for failure in batch.failures
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider, expected_host",
    [
        ("duckduckgo", "html.duckduckgo.com"),
        ("tavily", "api.tavily.com"),
        ("brave", "api.search.brave.com"),
    ],
)
async def test_selected_search_http_failure_never_calls_another_provider(
    tmp_path,
    monkeypatch,
    provider,
    expected_host,
):
    monkeypatch.setenv("TEST_SEARCH_KEY", "offline-test-key")
    requests = []

    def reject(request):
        requests.append(request)
        return httpx.Response(503, text="service unavailable")

    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(reject)

    def client_factory(*args, **kwargs):
        return client_type(*args, **kwargs, transport=transport)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    client = SearchClient(
        Settings(
            data_dir=tmp_path,
            search_provider=provider,
            search_api_key_env="TEST_SEARCH_KEY",
        )
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.search("free API official policy")
    assert [request.url.host for request in requests] == [expected_host]


@pytest.mark.asyncio
async def test_real_harness_memory_roundtrip_survives_new_researcher(tmp_path):
    settings = Settings(data_dir=tmp_path)
    note = "Official source leads require a fresh recheck; no candidate API was called."
    steps = iter(
        [
            ("write_memory", {"content": note, "file": "research-notes.md"}),
            ("read_memory", {"file": "research-notes.md"}),
        ]
    )
    write_results = []

    def writer(messages, info):
        write_results[:] = tool_results(messages)
        step = next(steps, None)
        if step:
            return ModelResponse([ToolCallPart(*step)])
        return ModelResponse(
            [
                ToolCallPart(
                    info.output_tools[0].name,
                    ResearchBatch().model_dump(mode="json"),
                )
            ]
        )

    first = HarnessResearcher(
        settings, model=FunctionModel(writer), search_client=cast(SearchClient, SearchTransport())
    )
    await first._build_agent().run("Write and read the research note.")
    assert any(
        note in str(part.content) for part in write_results if part.tool_name == "read_memory"
    )
    on_disk = tmp_path / "memory" / "policy-researcher" / "research-notes.md"
    assert on_disk.read_text(encoding="utf-8") == f"{note}\n"
    await first.memory_store.write(
        "policy-researcher/MEMORY.md",
        "Persistent checked-source index",
        expected_version=None,
    )

    read_results = []

    def reader(messages, info):
        read_results[:] = tool_results(messages)
        if not read_results:
            return ModelResponse([ToolCallPart("read_memory", {"file": "research-notes.md"})])
        return ModelResponse(
            [
                ToolCallPart(
                    info.output_tools[0].name,
                    ResearchBatch().model_dump(mode="json"),
                )
            ]
        )

    second = HarnessResearcher(
        settings, model=FunctionModel(reader), search_client=cast(SearchClient, SearchTransport())
    )
    result = await second._build_agent().run("Read the persisted research note.")
    assert any(note in str(part.content) for part in read_results)
    assert "Persistent checked-source index" in str(result.all_messages())
    stored = await second.memory_store.read(
        "policy-researcher/research-notes.md", max_chars=10_000,
    )
    assert stored is not None and stored.content == f"{note}\n"
    isolated = HarnessResearcher(
        Settings(data_dir=tmp_path / "isolated"),
        model=TestModel(call_tools=[], custom_output_args=ResearchBatch().model_dump(mode="json")),
        search_client=cast(SearchClient, SearchTransport()),
    )
    isolated_result = await isolated._build_agent().run("Read current memory context.")
    assert "Persistent checked-source index" not in str(isolated_result.all_messages())
    assert await isolated.memory_store.read(
        "policy-researcher/research-notes.md", max_chars=10_000,
    ) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["../escape.md", "/../escape.md", "C:/escape.md", "..\\escape.md"])
async def test_windows_memory_workspace_refuses_path_escape(tmp_path, path):
    workspace = MemoryWorkspace(tmp_path / "memory")
    await workspace.working_dir()
    with pytest.raises(ValueError):
        await workspace.write_bytes(path, b"must not escape")
    assert not (tmp_path / "escape.md").exists()


@pytest.mark.asyncio
async def test_memory_workspace_refuses_symlink_escape(tmp_path):
    root = tmp_path / "memory"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        (root / "leak").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink unavailable: {error}")
    workspace = MemoryWorkspace(root)
    await workspace.working_dir()
    with pytest.raises(ValueError, match="symlink"):
        await workspace.write_bytes("/leak/note.md", b"must not escape")
    assert not (outside / "note.md").exists()


class HTTPBoundary:
    """Script only the external HTTP socket boundary, never framework classes."""

    def __init__(self, body=QUOTE, *, location=None):
        self.body = body.encode()
        self.location = location
        self.connections = []

    def connection(self, host, port, **kwargs):
        boundary = self
        boundary.connections.append((host, port))

        class Connection:
            def request(self, method, target, headers):
                assert method == "GET"

            def getresponse(self):
                return boundary

            def close(self):
                pass

        return Connection()

    @property
    def status(self):
        return 302 if self.location else 200

    @property
    def headers(self):
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        return headers

    def getheader(self, key, default=None):
        return {"Location": self.location, "Content-Type": "text/html; charset=utf-8"}.get(
            key, default
        )

    def read(self, limit):
        return self.body[:limit]


@pytest.fixture
def public_dns(monkeypatch):
    def addresses(host, port, **kwargs):
        try:
            address = str(ipaddress.ip_address(host))
        except ValueError:
            address = "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", addresses)


@pytest.mark.asyncio
async def test_actual_page_fetch_strips_hidden_html_before_provenance(
    tmp_path, monkeypatch, public_dns
):
    boundary = HTTPBoundary(
        body=f"<html><script>Invented 999999 free requests</script><main>{QUOTE}</main></html>",
    )
    monkeypatch.setattr(http.client, "HTTPSConnection", boundary.connection)
    page = await PublicPageFetcher().fetch(SOURCE)
    assert page.text == QUOTE
    assert "999999" not in page.text
    researcher = HarnessResearcher(Settings(data_dir=tmp_path), model=TestModel())
    checked, errors = researcher.validate_policy(
        quoted_policy(), ResearchContext(pages={SOURCE: page})
    )
    assert checked.status == "active" and not errors


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://10.0.0.1/private",
        "http://169.254.169.254/latest",
        "http://[::1]/private",
        "http://localhost/private",
        "http://service.internal/private",
        "file:///C:/Windows/system.ini",
        "https://user:password@example.test/policy",
        "https://example.test:8443/policy",
        "https://example.test/v1/chat/completions",
        "https://example.test/register",
        "https://example.test/policy?api_key=secret",
    ],
)
async def test_local_private_and_action_urls_never_open_connection(monkeypatch, public_dns, url):
    opened = []

    def forbidden(*args, **kwargs):
        opened.append(args)
        raise AssertionError("Unsafe source opened an HTTP connection")

    monkeypatch.setattr(http.client, "HTTPSConnection", forbidden)
    monkeypatch.setattr(http.client, "HTTPConnection", forbidden)
    with pytest.raises((ResearchError, ValueError)):
        await PublicPageFetcher().fetch(url)
    assert not opened


@pytest.mark.asyncio
async def test_public_hostname_resolving_to_private_ip_is_rejected(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.1.2.3", 443)),
        ],
    )
    with pytest.raises(ResearchError, match="nonpublic"):
        await PublicPageFetcher().fetch(SOURCE)

@pytest.mark.asyncio
async def test_routable_address_is_used_when_ipv6_answer_is_synthetic(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("2001:2::10d", 443, 0, 0),
            ),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("28.0.1.13", 443)),
        ],
    )
    boundary = HTTPBoundary()
    monkeypatch.setattr(http.client, "HTTPSConnection", boundary.connection)
    page = await PublicPageFetcher().fetch(SOURCE)
    assert page.text == QUOTE
    assert boundary.connections == [("docs.example.test", 443)]


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["http://127.0.0.1/private", "http://169.254.169.254/latest"])
async def test_redirect_to_private_address_is_rejected_before_second_connection(
    monkeypatch,
    public_dns,
    location,
):
    boundary = HTTPBoundary(location=location)
    monkeypatch.setattr(http.client, "HTTPSConnection", boundary.connection)
    monkeypatch.setattr(http.client, "HTTPConnection", boundary.connection)
    with pytest.raises(ResearchError, match="nonpublic"):
        await PublicPageFetcher().fetch(SOURCE)
    assert boundary.connections == [("docs.example.test", 443)]


CLIP_MARKER = "\n[已截取与免费政策相关的段落；完整原文仅用于应用侧引文校验]"


@pytest.mark.asyncio
async def test_categories_research_concurrently(tmp_path, monkeypatch):
    search, fetch = SearchTransport(), SourceTransport()
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=TestModel(),
        search_client=cast(SearchClient, search),
        fetcher=cast(PublicPageFetcher, fetch),
    )
    entered = 0
    finished = 0
    both_entered = asyncio.Event()

    async def segment(prompt, **kwargs):
        nonlocal entered, finished
        entered += 1
        if entered == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=5)
        finished += 1
        return ResearchBatch(), ResearchContext(search_count=1)

    monkeypatch.setattr(researcher, "_segment", segment)
    batch = await researcher.research(Scope(categories=[Category.TEXT, Category.IMAGE]), [])
    assert both_entered.is_set()
    assert entered == 2 and finished == 2
    assert isinstance(batch, ResearchBatch)


@pytest.mark.asyncio
async def test_page_cache_prevents_repeated_transport_fetches(tmp_path):
    fetch = SourceTransport()
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=TestModel(),
        fetcher=cast(PublicPageFetcher, fetch),
    )
    first = await researcher._fetch_cached(SOURCE)
    second = await researcher._fetch_cached(SOURCE)
    assert len(fetch.calls) == 1
    assert first == second


def test_clip_for_model_keeps_policy_windows():
    long_text = ("填充内容 " * 4000) + "免费额度 1000 次/月" + ("结尾内容 " * 200)
    assert len(long_text) > 20_000
    clipped = clip_for_model(long_text)
    assert len(clipped) <= MODEL_PAGE_LIMIT + len(CLIP_MARKER)
    assert "免费额度" in clipped


@pytest.mark.asyncio
async def test_recheck_groups_batch_explicit_resources(tmp_path, monkeypatch):
    resources = [
        Resource(
            **quoted_policy(service=f"API {index}", service_key=f"api-{index}").model_dump(),
            id=f"existing-{index}",
        )
        for index in range(5)
    ]
    search, fetch = SearchTransport(), SourceTransport()
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=TestModel(),
        search_client=cast(SearchClient, search),
        fetcher=cast(PublicPageFetcher, fetch),
    )
    prompts = []

    async def segment(prompt, **kwargs):
        prompts.append(prompt)
        return (
            ResearchBatch(
                resources=[
                    quoted_policy(
                        service=resource.service,
                        service_key=resource.service_key,
                        resource_id=resource.id,
                    )
                    for resource in resources
                    if resource.id in prompt
                ]
            ),
            ResearchContext(),
        )

    monkeypatch.setattr(researcher, "_segment", segment)
    monkeypatch.setattr(researcher, "validate_policy", lambda policy, context: (policy, []))
    scope = Scope(categories=[Category.TEXT], resource_ids=[r.id for r in resources])
    batch = await researcher.research(scope, resources)
    expected_groups = -(-len(resources) // RECHECK_GROUP_SIZE)
    assert len(prompts) == expected_groups == 2
    assert all("Recheck exactly" in prompt for prompt in prompts)
    assert not any("EXISTING_OFFERS_JSON" in prompt for prompt in prompts)
    chunked = [
        [resource.id for resource in resources if resource.id in prompt] for prompt in prompts
    ]
    assert sorted(len(chunk) for chunk in chunked) == [1, RECHECK_GROUP_SIZE]
    returned_ids = [policy.resource_id for policy in batch.resources]
    assert all(rid is not None for rid in returned_ids)
    assert sorted(rid for rid in returned_ids if rid is not None) == sorted(
        resource.id for resource in resources
    )
    assert len(returned_ids) == len(set(returned_ids)) == len(resources)
    assert not batch.messages


@pytest.mark.asyncio
async def test_fetch_pages_returns_per_url_errors_and_caps(tmp_path):
    class SelectiveSourceTransport(SourceTransport):
        async def fetch(self, url):
            self.calls.append(url)
            if url == SOURCE:
                raise RuntimeError("source unavailable")
            return FetchedPage(url, self.text, CHECKED)

    fetch = SelectiveSourceTransport()
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=TestModel(),
        fetcher=cast(PublicPageFetcher, fetch),
    )
    other = "https://docs.example.test/other-api"
    urls = [SOURCE, other, *(f"https://docs.example.test/page-{index}" for index in range(1, 6))]
    capped = urls[MAX_BATCH_FETCH]
    assert capped not in urls[:MAX_BATCH_FETCH]
    context = ResearchContext()
    entries = {entry["url"]: entry for entry in await researcher.fetch_many(urls, context)}
    failure = f"Source retrieval failed for {SOURCE}: RuntimeError"
    assert entries[SOURCE]["error"] == failure
    assert entries[other] == {"url": other, "checked_at": CHECKED.isoformat(), "text": QUOTE}
    assert entries[capped]["error"] == f"batch fetch accepts at most {MAX_BATCH_FETCH} URLs"
    assert len(entries) == len(urls)
    assert set(fetch.calls) == set(urls[:MAX_BATCH_FETCH])
    assert capped not in fetch.calls
    assert failure in context.fetch_errors


@pytest.mark.asyncio
async def test_single_resource_scope_skips_discovery_and_rechecks_only_target(
    tmp_path, monkeypatch
):
    target = Resource(**quoted_policy().model_dump(), id="target-resource")
    peer = Resource(
        **quoted_policy(service="Peer API", service_key="peer-api").model_dump(),
        id="peer-resource",
    )
    search = SearchTransport()
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=TestModel(),
        search_client=cast(SearchClient, search),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )
    prompts = []

    async def segment(prompt, **kwargs):
        prompts.append(prompt)
        return (
            ResearchBatch(resources=[quoted_policy(resource_id=target.id)]),
            ResearchContext(pages={SOURCE: FetchedPage(SOURCE, QUOTE, CHECKED)}),
        )

    monkeypatch.setattr(researcher, "_segment", segment)
    monkeypatch.setattr(researcher, "validate_policy", lambda policy, context: (policy, []))
    batch = await researcher.research(
        Scope(categories=[Category.TEXT], resource_ids=[target.id]), [target, peer]
    )
    assert len(prompts) == 1
    assert "EXISTING_OFFERS_JSON" not in prompts[0]
    assert "Recheck exactly" in prompts[0]
    assert target.id in prompts[0]
    assert peer.id not in prompts[0]
    assert search.calls == []
    assert [policy.resource_id for policy in batch.resources] == [target.id]
    assert not batch.messages


def immediate_model():
    """Return an immediate empty research batch without any tool call."""

    def respond(messages, info):
        return ModelResponse(
            [
                ToolCallPart(
                    info.output_tools[0].name,
                    ResearchBatch().model_dump(mode="json"),
                )
            ]
        )

    return FunctionModel(respond)


class DirectTransport:
    """Serve robots.txt and direct pages without touching the network."""

    def __init__(self, links=(), robots="User-agent: *\nAllow: /\n"):
        self.links = tuple(links)
        self.robots = robots
        self.calls: list[str] = []

    async def fetch(self, url):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return FetchedPage(url, self.robots, CHECKED)
        return FetchedPage(url, "Pricing page text with 免费额度", CHECKED, self.links)


@pytest.mark.asyncio
async def test_discovery_prepends_fixed_baseline_queries_before_model(tmp_path):
    search = SearchTransport()
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=immediate_model(),
        search_client=cast(SearchClient, search),
        fetcher=cast(PublicPageFetcher, DirectTransport()),
        direct_interval=0,
    )

    await researcher.research(Scope(categories=[Category.TEXT]), [])

    expected = list(BASELINE_QUERIES[Category.TEXT])
    assert len(expected) == 6
    assert search.calls == expected
    cjk = [query for query in expected if any("\u4e00" <= char <= "\u9fff" for char in query)]
    assert cjk == expected[:3]
    assert not any("\u4e00" <= char <= "\u9fff" for query in expected[3:] for char in query)
    # Six of the sixteen search requests were spent before the model produced anything.
    assert researcher.last_stats.search_calls == 6


@pytest.mark.asyncio
async def test_direct_source_fetch_and_filtered_links_become_leads(tmp_path):
    entry = "https://example.com/pricing"
    links = ["https://example.com/docs/pricing", "https://other.test/pricing"]
    fetch = DirectTransport(links=links)
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path, direct_sources={"text": [entry]}),
        model=immediate_model(),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, fetch),
        direct_interval=0,
    )

    await researcher.research(Scope(categories=[Category.TEXT]), [])

    assert fetch.calls.count(entry) == 1
    assert fetch.calls.count("https://example.com/robots.txt") == 1
    direct = [lead for lead in researcher.last_discoveries if lead.origin == "direct"]
    link_leads = [lead for lead in researcher.last_discoveries if lead.origin == "link"]
    assert [(lead.url, lead.source_class) for lead in direct] == [(entry, "official-verifiable")]
    assert {lead.url: lead.source_class for lead in link_leads} == {
        links[0]: "official-verifiable",
        links[1]: "discovery-only",
    }


@pytest.mark.asyncio
async def test_robots_disallow_blocks_direct_fetch_and_records_note(tmp_path):
    entry = "https://example.com/pricing"
    fetch = DirectTransport(robots="User-agent: *\nDisallow: /pricing\n")
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path, direct_sources={"text": [entry]}),
        model=immediate_model(),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, fetch),
        direct_interval=0,
    )

    batch = await researcher.research(Scope(categories=[Category.TEXT]), [])

    assert entry not in fetch.calls
    assert any("robots.txt" in note for note in batch.notes)
    assert not any(lead.origin == "direct" for lead in researcher.last_discoveries)


@pytest.mark.asyncio
async def test_direct_sources_are_capped_at_max_direct_fetch(tmp_path):
    urls = [f"https://example.com/page-{index}" for index in range(MAX_DIRECT_FETCH + 1)]
    fetch = DirectTransport()
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path, direct_sources={"text": urls}),
        model=immediate_model(),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, fetch),
        direct_interval=0,
    )

    batch = await researcher.research(Scope(categories=[Category.TEXT]), [])

    page_calls = [call for call in fetch.calls if not call.endswith("/robots.txt")]
    assert len(page_calls) == MAX_DIRECT_FETCH == 8
    assert any("capped" in note.lower() for note in batch.notes)


@pytest.mark.asyncio
async def test_research_call_resets_previous_discoveries(tmp_path):
    entry = "https://example.com/pricing"
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path, direct_sources={"text": [entry]}),
        model=immediate_model(),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, DirectTransport()),
        direct_interval=0,
    )

    await researcher.research(Scope(categories=[Category.TEXT]), [])
    first_run = list(researcher.last_discoveries)
    assert first_run

    await researcher.research(Scope(categories=[Category.TEXT]), [])
    second_run = researcher.last_discoveries
    assert second_run is not first_run
    assert len(second_run) == len(first_run)


@pytest.mark.asyncio
async def test_recheck_segment_uses_no_baseline_queries_or_leads(tmp_path, monkeypatch):
    target = Resource(**quoted_policy().model_dump(), id="target-resource")
    search = SearchTransport()
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=TestModel(),
        search_client=cast(SearchClient, search),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
        direct_interval=0,
    )
    prompts = []

    async def segment(prompt, **kwargs):
        prompts.append(prompt)
        return (
            ResearchBatch(resources=[quoted_policy(resource_id=target.id)]),
            ResearchContext(pages={SOURCE: FetchedPage(SOURCE, QUOTE, CHECKED)}),
        )

    monkeypatch.setattr(researcher, "_segment", segment)
    monkeypatch.setattr(researcher, "validate_policy", lambda policy, context: (policy, []))

    await researcher.research(Scope(categories=[Category.TEXT], resource_ids=[target.id]), [target])

    assert search.calls == []
    assert researcher.last_discoveries == []
    assert len(prompts) == 1
    assert "BASELINE_RESULTS_JSON" not in prompts[0]


@pytest.mark.asyncio
async def test_collection_accepts_community_snippet_with_unknown_quota(tmp_path):
    message = collected_message(
        policy=reported_policy(
            docs_url="未说明",
            api_url="未说明",
            free_type="unknown",
            quota="未说明",
            quota_unit="未说明",
            refresh_cycle="未说明",
        ),
        sources=[
            MessageSource(
                url=COMMUNITY,
                title="Community report",
                excerpt=COMMUNITY_SNIPPET,
                source_type="community",
                access="snippet",
            )
        ],
    )
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=collection_model(message, fetch=False),
        search_client=cast(
            SearchClient,
            SearchTransport(
                rows=[
                    {
                        "title": "Community report",
                        "url": COMMUNITY,
                        "snippet": COMMUNITY_SNIPPET,
                    }
                ]
            ),
        ),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )
    batch = await researcher.research(Scope(categories=[Category.TEXT]), [])
    assert not batch.failures
    reported, = batch.messages
    assert reported.sources[0].access == "snippet"
    assert reported.sources[0].source_type == "community"
    assert reported.policy.quota == "未说明" and reported.policy.quota_unit == "未说明"


@pytest.mark.asyncio
async def test_collection_preserves_actual_snippet_when_page_fetch_fails(tmp_path):
    excerpt = "Example Developer API free tier provides 1000 requests per month."
    message = collected_message(
        sources=[
            MessageSource(
                url=SOURCE,
                title="Free API policy",
                excerpt=excerpt,
                source_type="official",
                access="page",
            )
        ]
    )
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=collection_model(message),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport(error=TimeoutError("offline"))),
    )
    batch = await researcher.research(Scope(categories=[Category.TEXT]), [])
    assert not batch.failures
    reported, = batch.messages
    assert reported.sources[0].access == "snippet"
    assert reported.sources[0].source_type == "search"
    assert reported.sources[0].excerpt == excerpt
    assert any("Retained actual search snippet" in note for note in batch.notes)
    assert any("Source retrieval failed" in note for note in batch.notes)


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["invented_url", "invented_page_quote", "invented_snippet"])
async def test_collection_rejects_invented_sources_and_quotes(tmp_path, defect):
    if defect == "invented_url":
        message = collected_message(
            sources=[
                MessageSource(
                    url="https://docs.example.test/never-fetched",
                    title="Invented page",
                    excerpt=QUOTE,
                    source_type="official",
                    access="page",
                )
            ]
        )
        fetch = False
    elif defect == "invented_page_quote":
        message = collected_message(
            sources=[
                MessageSource(
                    url=SOURCE,
                    title="Invented quote",
                    excerpt="Fabricated official quotation 999999 requests monthly.",
                    source_type="official",
                    access="page",
                )
            ]
        )
        fetch = True
    else:
        message = collected_message(
            sources=[
                MessageSource(
                    url=SOURCE,
                    title="Invented snippet",
                    excerpt="Fabricated snippet quotation 999999 requests monthly.",
                    source_type="search",
                    access="snippet",
                )
            ]
        )
        fetch = False
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=collection_model(message, fetch=fetch),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )
    batch = await researcher.research(Scope(categories=[Category.TEXT]), [])
    assert not batch.messages
    assert any("Discarded" in note for note in batch.notes)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url", ["http://127.0.0.1/private", "https://example.test/register"]
)
async def test_collection_discards_unsafe_source_urls(tmp_path, url):
    message = collected_message(
        sources=[
            MessageSource(
                url=url,
                title="Private network source",
                excerpt=QUOTE,
                source_type="official",
                access="page",
            )
        ]
    )
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=collection_model(message, fetch=False),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )

    batch = await researcher.research(Scope(categories=[Category.TEXT]), [])

    assert not batch.messages
    assert any("unsafe source URL" in note for note in batch.notes)


@pytest.mark.asyncio
async def test_collection_excludes_explicit_payment(tmp_path):
    message = collected_message(policy=reported_policy(payment_required=True))
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=collection_model(message),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )
    batch = await researcher.research(Scope(categories=[Category.TEXT]), [])
    assert not batch.messages
    assert any("付款" in note or "payment" in note.lower() for note in batch.notes)


@pytest.mark.asyncio
async def test_collection_excludes_web_only_free_offer(tmp_path):
    message = collected_message(
        policy=reported_policy(docs_url="未说明", api_url="未说明"),
        sources=[
            MessageSource(
                url=SOURCE,
                title="Free image generator",
                excerpt=WEB_ONLY_TEXT,
                source_type="community",
                access="page",
            )
        ],
    )
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=collection_model(message),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport(text=WEB_ONLY_TEXT)),
    )
    batch = await researcher.research(Scope(categories=[Category.TEXT]), [])
    assert not batch.messages
    assert any("免费 API" in note for note in batch.notes)


@pytest.mark.asyncio
async def test_collection_allows_required_card_without_payment(tmp_path):
    message = collected_message(policy=reported_policy(payment_method_required=True))
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=collection_model(message),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )
    batch = await researcher.research(Scope(categories=[Category.TEXT]), [])
    reported, = batch.messages
    assert reported.policy.payment_required is False
    assert reported.policy.payment_method_required is True


@pytest.mark.asyncio
async def test_collection_prompt_reuses_known_ids_and_offer_keys_without_rechecks(
    tmp_path, monkeypatch
):
    known = Resource(
        **reported_policy().model_dump(),
        id="known-resource",
        messages=[collected_message()],
    )
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=TestModel(),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )
    prompts = []

    async def segment(prompt, **kwargs):
        prompts.append(prompt)
        return ResearchBatch(), ResearchContext(search_count=1)

    monkeypatch.setattr(researcher, "_segment", segment)
    batch = await researcher.research(Scope(categories=[Category.TEXT]), [known])
    assert not batch.resources
    prompt, = prompts
    assert "EXISTING_OFFERS_JSON" in prompt
    assert "known-resource" in prompt
    assert "developer-api" in prompt
    assert "developer-free" in prompt
    assert "Recheck exactly" not in prompt


@pytest.mark.asyncio
async def test_collection_binds_known_resource_update_without_rechecking(tmp_path):
    known = Resource(**reported_policy().model_dump(), id="known-resource")
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=collection_model(collected_message()),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )

    batch = await researcher.research(Scope(categories=[Category.TEXT]), [known])

    assert not batch.failures
    updated, = batch.messages
    assert updated.policy.resource_id == known.id
    assert updated.policy.status == "pending"
    assert updated.policy.check_status == "incomplete"


@pytest.mark.asyncio
async def test_collection_uses_light_budgets_and_collection_instructions(
    tmp_path, monkeypatch
):
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=TestModel(),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )
    seen = {}

    async def segment(prompt, **kwargs):
        seen.update(kwargs)
        return ResearchBatch(), ResearchContext(search_count=1)

    monkeypatch.setattr(researcher, "_segment", segment)
    await researcher.research(Scope(categories=[Category.TEXT]), [])

    assert seen["instructions"] == COLLECTION_INSTRUCTIONS
    assert seen["search_budget"] == MAX_COLLECTION_SEARCH
    assert seen["fetch_budget"] == MAX_COLLECTION_FETCH
    assert seen["page_limit"] == COLLECTION_PAGE_LIMIT
    assert seen["search_budget"] < MAX_VERIFY_SEARCH
    assert seen["fetch_budget"] < MAX_VERIFY_FETCH
    assert seen["page_limit"] < MODEL_PAGE_LIMIT


@pytest.mark.asyncio
async def test_research_merges_collected_messages_from_categories(tmp_path, monkeypatch):
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=TestModel(),
        search_client=cast(SearchClient, SearchTransport()),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )

    async def segment(prompt, **kwargs):
        category = "text" if "free text API offers" in prompt else "image"
        return (
            ResearchBatch(
                messages=[collected_message(policy=reported_policy(category=category))]
            ),
            ResearchContext(
                search_count=1,
                pages={SOURCE: FetchedPage(SOURCE, QUOTE, CHECKED)},
            ),
        )

    monkeypatch.setattr(researcher, "_segment", segment)
    batch = await researcher.research(Scope(categories=[Category.TEXT, Category.IMAGE]), [])
    assert sorted(message.policy.category for message in batch.messages) == ["image", "text"]
    assert not batch.failures


@pytest.mark.asyncio
async def test_fetch_budget_counts_actual_attempts_without_repeated_errors(tmp_path):
    fetch = SourceTransport()
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=TestModel(),
        fetcher=cast(PublicPageFetcher, fetch),
    )
    context = ResearchContext(fetch_budget=1)
    first = await researcher.fetch_many([SOURCE], context)
    assert first[0]["url"] == SOURCE
    assert context.fetch_count == 1
    await researcher.fetch_many([SOURCE], context)
    assert context.fetch_count == 1
    other = "https://docs.example.test/other-api"
    third = "https://docs.example.test/third-api"
    assert (await researcher.fetch_many([other], context))[0]["error"]
    assert (await researcher.fetch_many([third], context))[0]["error"]
    assert context.fetch_count == 1
    budget_notes = [note for note in context.notes if "budget was exhausted" in note]
    assert len(budget_notes) == 1
    assert not context.fetch_errors


@pytest.mark.asyncio
async def test_search_budget_is_presented_and_refused_once(tmp_path):
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=TestModel(),
        fetcher=cast(PublicPageFetcher, SourceTransport()),
    )
    search = SearchTransport()
    researcher._search = cast(SearchClient, search)
    context = ResearchContext(search_budget=1)
    prepared = await researcher._discovery_prepass(Category.TEXT, context)
    assert search.calls == [BASELINE_QUERIES[Category.TEXT][0]]
    assert "searches_remaining=0" in prepared
    assert len([note for note in context.notes if "search request budget" in note]) == 1


def test_validate_message_requires_observed_end_reason(tmp_path):
    researcher = HarnessResearcher(Settings(data_dir=tmp_path))
    context = ResearchContext(pages={SOURCE: FetchedPage(SOURCE, QUOTE, CHECKED)})

    unsupported = collected_message(ended=True, end_reason="官方公告停止免费额度")
    checked, notes = researcher.validate_message(unsupported, context)
    assert checked is not None
    assert checked.ended is False
    assert checked.end_reason == ""
    assert any("end reason absent" in note for note in notes)

    leftover = collected_message(ended=False, end_reason="leftover")
    checked, _ = researcher.validate_message(leftover, context)
    assert checked is not None
    assert checked.end_reason == ""

    supported_text = QUOTE + " The Developer API free tier has ended."
    context.pages[SOURCE] = FetchedPage(SOURCE, supported_text, CHECKED)
    supported = collected_message(
        sources=[MessageSource(url=SOURCE, excerpt=supported_text, access="page")],
        ended=True,
        end_reason="The Developer API free tier has ended",
    )
    checked, notes = researcher.validate_message(supported, context)
    assert checked is not None
    assert checked.ended is True
    assert checked.end_reason == "The Developer API free tier has ended"


def test_message_source_rejects_credential_url():
    with pytest.raises(ValidationError):
        MessageSource(
            url="https://user:password@example.test/policy",
            excerpt="Free API documentation is available.",
        )


@pytest.mark.asyncio
async def test_source_collection_targets_historical_service_and_accepts_unknown_conditions(tmp_path):
    target = Resource(**reported_policy().model_dump(), id="historical-api", first_seen_at=CHECKED)
    message = collected_message(
        policy=reported_policy(
            resource_id=target.id, free_type="unknown", api_url="未说明", docs_url="未说明",
            quota="未说明", quota_unit="未说明", payment_required=None, payment_method_required=None,
        ),
        sources=[MessageSource(url=COMMUNITY, excerpt=COMMUNITY_SNIPPET, source_type="community")],
    )
    search = SearchTransport(rows=[{
        "title": "Community free API report", "url": COMMUNITY, "snippet": COMMUNITY_SNIPPET,
    }])
    prompts = []
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        model=collection_model(message, fetch=False, prompts=prompts),
        search_client=cast(SearchClient, search),
    )
    batch = await researcher.collect_sources([target])
    assert not batch.resources and not batch.failures
    (accepted,) = batch.messages
    assert accepted.policy.resource_id == target.id
    assert accepted.policy.free_type == "unknown" and accepted.policy.quota == "未说明"
    assert accepted.policy.status == "pending" and accepted.sources[0].access == "snippet"
    assert len(search.calls) == 1 and target.provider in search.calls[0] and target.service in search.calls[0]
    assert all("SOURCE_TARGETS_JSON" in prompt for prompt in prompts)
    assert not any("RECHECK_RESOURCES_JSON" in prompt or "BASELINE_RESULTS_JSON" in prompt for prompt in prompts)
    assert researcher.last_stats.search_calls == 1 and researcher.last_stats.fetch_calls == 0


@pytest.mark.asyncio
async def test_source_collection_with_no_missing_records_needs_no_model_or_search_credentials(tmp_path):
    researcher = HarnessResearcher(Settings(data_dir=tmp_path, model_api_key_env="MISSING_BACKFILL_KEY"))
    assert not (await researcher.collect_sources([])).messages
    already_collected = Resource(
        **reported_policy().model_dump(), id="already-collected", messages=[collected_message()]
    )
    batch = await researcher.collect_sources([already_collected])
    assert not batch.messages and not batch.failures
    assert researcher.last_stats == RunStats()


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["unrelated_service", "unobserved_quote"])
async def test_source_collection_never_imports_unrelated_or_fabricated_reports(tmp_path, defect):
    target = Resource(**reported_policy().model_dump(), id="historical-api")
    message = collected_message(
        policy=reported_policy(resource_id=target.id),
        sources=[MessageSource(url=COMMUNITY, excerpt=COMMUNITY_SNIPPET)],
    )
    if defect == "unrelated_service":
        message.policy.service_key = "a-different-api"
    else:
        message.sources[0].excerpt = "An invented free API report absent from the actual search result"
    search = SearchTransport(rows=[{
        "title": "Community free API report", "url": COMMUNITY, "snippet": COMMUNITY_SNIPPET,
    }])
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path), model=collection_model(message, fetch=False),
        search_client=cast(SearchClient, search),
    )
    batch = await researcher.collect_sources([target])
    assert not batch.messages and not batch.resources
    assert not batch.failures and batch.notes


@pytest.mark.asyncio
async def test_source_collection_cancelled_during_target_search_records_actual_usage(tmp_path):
    entered = asyncio.Event()

    class BlockingSearch(SearchTransport):
        async def search(self, query):
            self.calls.append(query)
            entered.set()
            await asyncio.Event().wait()
            return []

    search = BlockingSearch()
    target = Resource(**reported_policy().model_dump(), id="historical-api")
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path), model=immediate_model(), search_client=cast(SearchClient, search),
    )
    task = asyncio.create_task(researcher.collect_sources([target]))
    await asyncio.wait_for(entered.wait(), timeout=3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert researcher.last_stats.search_calls == 1
    assert researcher.last_stats.model_requests == researcher.last_stats.fetch_calls == 0
