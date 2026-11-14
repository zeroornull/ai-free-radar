"""C-owned regressions: planning, source observations, safe transport, and run traces."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import cast

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from aifreeradar.config import Settings
from aifreeradar.models import (
    Category,
    CollectedMessage,
    MessageSource,
    ModelDeployment,
    Policy,
    QuotaFact,
    ResearchBatch,
    ResearchGap,
    ResearchTrace,
    RunStats,
    Scope,
    SourceDefinition,
    SourceEntry,
    SourceSnapshot,
)
from aifreeradar.research import (
    BASELINE_QUERIES,
    PRODUCT_BASELINE_QUERIES,
    FetchedPage,
    HarnessResearcher,
    PublicPageFetcher,
    ResearchContext,
    ResearchError,
    SearchClient,
)
from aifreeradar.research_planning import (
    DeploymentCandidate,
    ObservedText,
    QuotaCandidate,
    evaluate_gap_outcome,
    evaluate_model_deployment,
    evaluate_quota_fact,
    plan_gap_queries,
)
from aifreeradar.service import TaskManager
from aifreeradar.sources import SourceScan
from aifreeradar.storage import Repository

CHECKED = datetime(2026, 11, 14, 4, tzinfo=UTC)
SOURCE = "https://example.com/pricing"
ENTRY_URL = "https://example.com/blog/free-credits"
QUOTE = (
    "New accounts receive 500 credits per month for the free API without a credit card."
)


def reported_policy(**updates):
    values = {
        "provider": "Example Provider",
        "service": "Developer API",
        "category": Category.TEXT,
        "provider_domain": "example.com",
        "service_key": "developer-api",
        "free_type": "limited",
        "quota": "500",
        "quota_unit": "credits",
    }
    values.update(updates)
    return Policy(**values)


def collected_message(sources, policy=None, **updates):
    values = {
        "policy": policy or reported_policy(),
        "offer_key": "developer-credits",
        "title": "Free credits",
        "summary": "500 free API credits every month.",
        "sources": sources,
    }
    values.update(updates)
    return CollectedMessage(**values)


def test_planner_derives_alias_and_credit_queries_once():
    rows = [
        {
            "url": "https://alpha.example.com/pricing",
            "title": "Alpha free credits and formerly Beta API",
            "snippet": "Alpha offers trial credits for new accounts.",
            "source_id": "feed-1",
        },
        {
            "url": "https://alpha.example.com/pricing",
            "title": "Alpha free credits again",
            "snippet": "Same campaign, duplicate row.",
        },
        {
            "url": "https://plain.example.net/docs",
            "title": "Plain documentation",
            "snippet": "No offer wording here.",
        },
    ]

    gaps = plan_gap_queries(Category.TEXT, rows, limit=3)

    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.category is Category.TEXT
    assert gap.trigger_url == rows[0]["url"]
    assert gap.source_ids == ["feed-1"]
    assert "Beta API" in gap.query
    assert "credits" in gap.query.casefold()
    assert gap.id == plan_gap_queries(Category.TEXT, rows, limit=3)[0].id
    assert plan_gap_queries(Category.TEXT, rows, seen_queries=[gap.query]) == []
    assert plan_gap_queries(Category.TEXT, rows, limit=0) == []


def test_planner_uses_observed_free_wording_not_assumed_tier():
    rows = [
        {
            "url": "https://trial.example.org/offer",
            "title": "Trial credits",
            "snippet": "试用赠额 available.",
        }
    ]

    gap = plan_gap_queries(Category.TEXT, rows, limit=1)[0]

    assert "trial credits" in gap.query.casefold()
    assert "free tier" not in gap.query.casefold()
    assert gap.goal


def test_gap_outcome_never_resolves_on_a_new_search_url_alone():
    outcome = evaluate_gap_outcome(
        result_rows=[{"url": "https://new.example.com/pricing", "snippet": "free"}],
    )
    assert outcome.stop_reason == "no_new_evidence"
    assert outcome.new_result_urls == ["https://new.example.com/pricing"]
    assert outcome.new_evidence_urls == []

    read = evaluate_gap_outcome(
        result_rows=[{"url": "https://new.example.com/pricing"}],
        read_pages=[("https://new.example.com/pricing", QUOTE)],
    )
    assert read.stop_reason == "gap_resolved"
    assert read.new_evidence_urls == ["https://new.example.com/pricing"]

    known = evaluate_gap_outcome(
        result_rows=[{"url": "https://new.example.com/pricing"}],
        known_urls=["https://new.example.com/pricing"],
    )
    assert known.stop_reason == "no_new_evidence"


def test_gap_outcome_distinguishes_failure_and_budget_stops():
    assert evaluate_gap_outcome(search_failed=True).stop_reason == "provider_failed"
    assert evaluate_gap_outcome(search_budget_exhausted=True).stop_reason == "budget_exhausted"
    exhausted = evaluate_gap_outcome(
        result_rows=[{"url": "https://new.example.com/pricing"}],
        read_pages=[],
        fetch_budget_exhausted=True,
    )
    assert exhausted.stop_reason == "budget_exhausted"
    assert evaluate_gap_outcome(duplicate_query=True).stop_reason == "duplicate_query"


def test_quota_fact_requires_quote_units_and_page_source():
    page = ObservedText(url=SOURCE, text=QUOTE, access="page")
    fact = QuotaCandidate(
        source_url=SOURCE,
        quote=QUOTE,
        amount=500,
        unit="credits",
        condition="new accounts",
    )
    assert evaluate_quota_fact(fact, [page]).accepted
    wrong_amount = QuotaCandidate(
        source_url=SOURCE, quote=QUOTE, amount=900, unit="credits"
    )
    assert not evaluate_quota_fact(wrong_amount, [page]).accepted
    wrong_unit = QuotaCandidate(source_url=SOURCE, quote=QUOTE, amount=500, unit="tokens")
    assert not evaluate_quota_fact(wrong_unit, [page]).accepted
    catalog = ObservedText(url=SOURCE, text=QUOTE, access="catalog")
    assert not evaluate_quota_fact(fact, [catalog]).accepted
    missing_observation = evaluate_quota_fact(fact, [])
    assert not missing_observation.accepted
    assert missing_observation.warning


def test_model_deployment_requires_exact_observed_mapping():
    text = "Example Provider offers model-x and base-x on its API."
    observed = ObservedText(url=SOURCE, text=text, access="page")
    deployment = DeploymentCandidate(
        source_url=SOURCE,
        quote=text,
        provider="Example Provider",
        model_id="model-x",
        base_model="base-x",
    )
    assert evaluate_model_deployment(deployment, [observed]).accepted
    fuzzy = DeploymentCandidate(
        source_url=SOURCE,
        quote=text,
        provider="Example",
        model_id="model-y",
        base_model="base-x",
    )
    assert not evaluate_model_deployment(fuzzy, [observed]).accepted


def test_fetched_page_defaults_and_conditional_header_allowlist():
    page = FetchedPage(url=SOURCE, text="policy")
    assert page.raw_content == ""
    assert page.content_type == "text/plain"
    assert page.status_code == 200
    assert page.etag == "" and page.last_modified == ""

    fetcher = PublicPageFetcher()
    with pytest.raises(ResearchError, match="conditional"):
        fetcher._fetch(SOURCE, headers={"Authorization": "secret"})
    with pytest.raises(ResearchError, match="conditional"):
        fetcher._fetch(SOURCE, headers={"If-None-Match": 'bad"\nvalue'})


class ConditionalTransport:
    def __init__(self, status=304, text=""):
        self.status = status
        self.text = text
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def fetch(self, url, *, headers=None):
        self.calls.append((url, dict(headers or {})))
        if url.endswith("/robots.txt"):
            return FetchedPage(url, "User-agent: *\nAllow: /\n", CHECKED)
        return FetchedPage(
            url,
            self.text,
            CHECKED,
            status_code=self.status,
            etag='"revision-2"',
        )


@pytest.mark.asyncio
async def test_conditional_304_restores_cached_body_and_reuses_attempt(tmp_path):
    transport = ConditionalTransport()
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        fetcher=cast(PublicPageFetcher, transport),
        direct_interval=0,
    )
    researcher._page_cache[SOURCE] = FetchedPage(SOURCE, "cached body", CHECKED)
    context = ResearchContext(fetch_budget=5)

    first = await researcher._source_fetch_page(
        SOURCE, {"If-None-Match": '"revision-1"'}, context
    )
    second = await researcher._source_fetch_page(
        SOURCE, {"If-None-Match": '"revision-1"'}, context
    )

    assert first.status_code == 304
    assert first.text == "cached body"
    assert second.text == "cached body"
    page_calls = [call for call in transport.calls if not call[0].endswith("/robots.txt")]
    assert page_calls == [(SOURCE, {"If-None-Match": '"revision-1"'})]
    # robots.txt and one conditional page consumed exactly two segment fetches.
    assert context.fetch_count == 2


@pytest.mark.asyncio
async def test_conditional_304_without_cached_body_stays_bodyless(tmp_path):
    transport = ConditionalTransport()
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path),
        fetcher=cast(PublicPageFetcher, transport),
        direct_interval=0,
    )
    context = ResearchContext(fetch_budget=5)

    page = await researcher._source_fetch_page(SOURCE, {"If-None-Match": '"v1"'}, context)

    assert page.status_code == 304
    assert page.text == ""
    assert any("304" in note for note in context.notes)


class FakePipeline:
    def __init__(self, scan):
        self.scan = scan
        self.runs: list[str] = []
        self.collected = 0

    def begin_run(self, run_id=""):
        self.runs.append(run_id)

    async def collect(self, category, fetch, *, run_id=""):
        self.collected += 1
        assert callable(fetch)
        return self.scan


@pytest.mark.asyncio
async def test_source_prepass_registers_web_page_and_feed_ledger(tmp_path):
    web = SourceDefinition(
        id="web-1",
        name="Pricing",
        url=SOURCE,
        kind="web",
        categories=[Category.TEXT],
        source_type="official",
        official_domain="example.com",
    )
    feed = SourceDefinition(
        id="feed-1",
        name="Blog",
        url="https://example.com/feed.xml",
        kind="feed",
        categories=[Category.TEXT],
    )
    snapshot = SourceSnapshot(
        source_id=web.id,
        url=SOURCE,
        fetched_at=CHECKED,
        raw_content="<html><body>Free 100 API calls per day</body></html>",
        content_type="text/html",
        text="Free 100 API calls per day",
        links=["https://example.com/docs/pricing", "https://other.test/pricing"],
        raw_hash="raw",
        normalized_hash="normalized",
        config_hash="config",
    )
    entry = SourceEntry(
        source_id=feed.id,
        external_id="post-1",
        url=ENTRY_URL,
        title="Free credits",
        content=QUOTE,
        raw_content=QUOTE,
    )
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path, sources=[web, feed]),
        fetcher=cast(PublicPageFetcher, ConditionalTransport(status=200, text="unused")),
        direct_interval=0,
    )
    researcher._pipeline = FakePipeline(
        SourceScan(entries=[entry], snapshots=[snapshot], notes=["来源健康：ok"])
    )
    researcher._source_urls_requested.add(SOURCE)
    context = ResearchContext()

    text = await researcher._source_prepass(Category.TEXT, context, 500)

    assert context.pages[SOURCE].text == "Free 100 API calls per day"
    assert [row.external_id for row in context.source_observations] == ["post-1"]
    assert "SOURCE_PAGES_JSON" in text and "SOURCE_ITEMS_JSON" in text
    assert "post-1" in text and "来源健康：ok" in context.notes
    direct = [lead for lead in researcher.last_discoveries if lead.origin == "direct"]
    assert [(lead.url, lead.source_class) for lead in direct] == [
        (SOURCE, "official-verifiable")
    ]
    feed_leads = [lead for lead in researcher.last_discoveries if lead.origin == "feed"]
    assert {lead.url for lead in feed_leads} == {"https://example.com/feed.xml", ENTRY_URL}


@pytest.mark.asyncio
async def test_source_entries_precede_and_survive_model_failure(tmp_path):
    web = SourceDefinition(
        id="web-1",
        name="Pricing",
        url=SOURCE,
        kind="web",
        categories=[Category.TEXT],
        source_type="official",
        official_domain="example.com",
    )
    feed = SourceDefinition(
        id="feed-1",
        name="Blog",
        url="https://example.com/feed.xml",
        kind="feed",
        categories=[Category.TEXT],
    )
    entry = SourceEntry(
        source_id=feed.id,
        external_id="post-1",
        url=ENTRY_URL,
        title="Free credits",
        content=QUOTE,
        raw_content=QUOTE,
    )
    pipeline = FakePipeline(SourceScan(entries=[entry], notes=["来源健康：ok"]))

    def unavailable(messages, info):
        raise RuntimeError("model offline")

    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path, sources=[web, feed]),
        model=FunctionModel(unavailable),
        search_client=cast(SearchClient, GapSearch(rows=[])),
        fetcher=cast(PublicPageFetcher, GapTransport(text="unused")),
        direct_interval=0,
    )
    researcher._pipeline = pipeline

    batch = await researcher.research(Scope(categories=[Category.TEXT]), [])

    # Raw source collection ran exactly once before the model was attempted, and
    # its gap trace survives the model failure for the task ledger.
    assert pipeline.collected == 1
    assert pipeline.runs == [""]
    assert any("research segment failed" in failure for failure in batch.failures)
    assert researcher.last_research_traces
    assert researcher.last_research_traces[0].stop_reason == "no_new_evidence"


def test_validate_message_accepts_feed_and_catalog_but_not_fake_pages(tmp_path):
    feed = SourceDefinition(
        id="feed-1",
        name="Blog",
        url="https://example.com/feed.xml",
        kind="feed",
        categories=[Category.TEXT],
    )
    catalog = SourceDefinition(
        id="catalog-1",
        name="Catalog",
        url="https://models.example.com/api.json",
        kind="catalog",
        categories=[Category.TEXT],
        source_type="catalog",
    )
    researcher = HarnessResearcher(Settings(data_dir=tmp_path))
    researcher._source_definitions = {feed.id: feed, catalog.id: catalog}
    feed_entry = SourceEntry(
        source_id=feed.id,
        external_id="post-1",
        url=ENTRY_URL,
        title="Free credits",
        content=QUOTE,
        raw_content=QUOTE,
    )
    catalog_entry = feed_entry.model_copy(
        update={"source_id": catalog.id, "external_id": "record-1"}
    )
    context = ResearchContext(source_observations=[feed_entry, catalog_entry])

    feed_source = MessageSource(
        url=ENTRY_URL,
        excerpt="500 credits per month for the free API",
        access="feed",
        source_id=feed.id,
        external_id="post-1",
    )
    checked, notes = researcher.validate_message(
        collected_message([feed_source]), context
    )
    assert checked is not None
    assert checked.sources[0].access == "feed"
    assert checked.sources[0].source_id == feed.id
    assert checked.sources[0].source_type == "community"
    assert notes == []

    catalog_source = feed_source.model_copy(
        update={"access": "catalog", "source_id": catalog.id, "external_id": "record-1"}
    )
    checked, _ = researcher.validate_message(
        collected_message([catalog_source]), context
    )
    assert checked is not None
    assert checked.sources[0].source_type == "catalog"

    fake_page = feed_source.model_copy(update={"access": "page"})
    checked, notes = researcher.validate_message(
        collected_message([fake_page]), context
    )
    assert checked is None
    assert any("unobserved" in note for note in notes)


def test_optional_facts_need_observed_evidence_and_never_reject_message(tmp_path):
    researcher = HarnessResearcher(Settings(data_dir=tmp_path))
    researcher._source_definitions = {}
    context = ResearchContext(
        pages={
            SOURCE: FetchedPage(
                SOURCE,
                QUOTE + " Example Provider offers model-x on base-x.",
                CHECKED,
            )
        }
    )
    source = MessageSource(
        url=SOURCE,
        excerpt="500 credits per month for the free API",
        access="page",
        source_type="official",
    )
    quota = QuotaFact(
        amount=500,
        unit="credits",
        period="month",
        condition="new accounts",
        source_url=SOURCE,
        quote="New accounts receive 500 credits",
        value_phrase="500 credits",
    )
    deployment = ModelDeployment(
        provider="Example Provider",
        model_id="model-x",
        base_model="base-x",
        source_url=SOURCE,
        quote="Example Provider offers model-x on base-x",
    )
    supported = reported_policy(quota_facts=[quota], model_deployments=[deployment])

    checked, _ = researcher.validate_message(
        collected_message([source], policy=supported), context
    )
    assert checked is not None
    assert checked.policy.quota_facts == [quota]
    assert checked.policy.model_deployments == [deployment]
    assert checked.policy.fact_warnings == []

    unsupported_quota = quota.model_copy(update={"amount": 9999})
    unsupported = reported_policy(quota_facts=[unsupported_quota])
    checked, _ = researcher.validate_message(
        collected_message([source], policy=unsupported), context
    )
    assert checked is not None
    assert checked.policy.quota_facts == []
    assert checked.policy.fact_warnings
    assert "额度" in checked.policy.fact_warnings[0]


class GapSearch:
    def __init__(self, rows=None, error=None):
        self.rows = rows if rows is not None else []
        self.error = error
        self.calls: list[str] = []

    async def search(self, query):
        self.calls.append(query)
        if self.error:
            raise self.error
        return list(self.rows)


class GapTransport:
    def __init__(self, text=QUOTE, error=None):
        self.text = text
        self.error = error
        self.calls: list[str] = []

    async def fetch(self, url):
        self.calls.append(url)
        if self.error:
            raise self.error
        return FetchedPage(url, self.text, CHECKED)


def gap() -> ResearchGap:
    return ResearchGap(
        id="gap-1",
        category=Category.TEXT,
        query='"example.com" free credits API quota documentation',
        goal="补全额度原文",
        trigger_url=SOURCE,
    )


@pytest.mark.asyncio
async def test_gap_execution_fetches_only_new_candidates(tmp_path):
    search = GapSearch(
        rows=[
            {"title": "Known", "url": SOURCE, "snippet": "known"},
            {"title": "New", "url": "https://new.example.net/pricing", "snippet": "500 free credits"},
        ]
    )
    transport = GapTransport()
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path, gap_search_limit=3),
        search_client=cast(SearchClient, search),
        fetcher=cast(PublicPageFetcher, transport),
        direct_interval=0,
    )
    context = ResearchContext(
        pages={SOURCE: FetchedPage(SOURCE, "known", CHECKED)},
        search_budget=4,
        fetch_budget=4,
    )

    traces = await researcher._execute_gap_queries(Category.TEXT, context, [gap()])

    assert transport.calls == ["https://new.example.net/pricing"]
    assert traces[0].stop_reason == "gap_resolved"
    assert traces[0].new_evidence_urls == ["https://new.example.net/pricing"]
    assert traces[0].search_calls == 1
    assert traces[0].gap_id == "gap-1"
    assert context.research_traces == []


@pytest.mark.asyncio
async def test_gap_execution_traces_provider_and_budget_stops(tmp_path):
    failed = HarnessResearcher(
        Settings(data_dir=tmp_path),
        search_client=cast(SearchClient, GapSearch(error=RuntimeError("boom"))),
        fetcher=cast(PublicPageFetcher, GapTransport()),
        direct_interval=0,
    )
    context = ResearchContext(search_budget=2, fetch_budget=2)
    traces = await failed._execute_gap_queries(Category.TEXT, context, [gap()])
    assert traces[0].stop_reason == "provider_failed"
    assert context.failures

    exhausted = HarnessResearcher(
        Settings(data_dir=tmp_path),
        search_client=cast(SearchClient, GapSearch(rows=[{"url": SOURCE}])),
        fetcher=cast(PublicPageFetcher, GapTransport()),
        direct_interval=0,
    )
    traces = await exhausted._execute_gap_queries(
        Category.TEXT, ResearchContext(search_budget=0), [gap()]
    )
    assert traces[0].stop_reason == "budget_exhausted"
    assert traces[0].search_calls == 0


def immediate_model():
    def respond(messages, info):
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result", ResearchBatch().model_dump(mode="json")
                )
            ]
        )

    return FunctionModel(respond)


@pytest.mark.asyncio
async def test_research_releases_run_cache_after_collection(tmp_path):
    researcher = HarnessResearcher(
        Settings(data_dir=tmp_path, gap_search_limit=0),
        model=immediate_model(),
        search_client=cast(
            SearchClient,
            GapSearch(rows=[{"title": "Docs", "url": SOURCE, "snippet": "no offer"}]),
        ),
        fetcher=cast(PublicPageFetcher, GapTransport(text="Pricing page")),
        direct_interval=0,
    )

    await researcher.research(Scope(categories=[Category.TEXT]), [])

    assert researcher._page_cache == {}
    assert researcher._fetch_locks == {}
    assert researcher._conditional_cache == {}
    assert researcher.last_stats.search_calls == len(BASELINE_QUERIES[Category.TEXT]) + len(
        PRODUCT_BASELINE_QUERIES[Category.TEXT]
    )
    assert isinstance(researcher.last_research_traces, list)


class TraceResearcher:
    def __init__(self, traces, error=None):
        self.last_stats = RunStats()
        self.last_discoveries = []
        self.last_research_traces = traces
        self.error = error
        self.ids: list[str] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    def set_run_id(self, run_id):
        self.ids.append(run_id)

    async def research(self, scope, existing):
        self.entered.set()
        await self.release.wait()
        if self.error is not None:
            raise self.error
        return ResearchBatch()


def trace(secret: str) -> ResearchTrace:
    return ResearchTrace(
        gap_id="gap-1",
        category=Category.TEXT,
        query=f"free credits {secret}",
        goal="goal",
        trigger_url=SOURCE,
        result_urls=[SOURCE],
        stop_reason="no_new_evidence",
    )


@pytest.mark.asyncio
async def test_task_manager_attaches_redacted_traces_on_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("RADAR_SECRET_KEY", "trace-secret-value")
    settings = Settings(data_dir=tmp_path)
    repository = Repository(settings.data_dir)
    researcher = TraceResearcher([trace("trace-secret-value")], error=RuntimeError("failed"))
    researcher.release.set()
    manager = TaskManager(settings, repository, researcher)
    try:
        run = await manager.start(Scope(categories=[Category.TEXT]))
        await manager.wait_idle()
        saved = repository.get_run(run.id)
        assert saved is not None and saved.status == "failed"
        assert researcher.ids == [run.id]
        assert len(saved.research_traces) == 1
        assert "trace-secret-value" not in json.dumps(
            saved.research_traces[0].model_dump(mode="json"), ensure_ascii=False
        )
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_task_manager_attaches_traces_when_cancelled(tmp_path):
    settings = Settings(data_dir=tmp_path)
    repository = Repository(settings.data_dir)
    researcher = TraceResearcher([trace("no-secret")])
    manager = TaskManager(settings, repository, researcher)
    run = await manager.start(Scope(categories=[Category.TEXT]))
    await asyncio.wait_for(researcher.entered.wait(), timeout=3)
    await manager.close()
    saved = repository.get_run(run.id)
    assert saved is not None
    assert saved.status == "failed"
    assert len(saved.research_traces) == 1
