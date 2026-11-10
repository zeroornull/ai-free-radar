"""Rendered and persisted discovery leads in briefings."""

from __future__ import annotations

from pathlib import Path

import pytest
from domain_fixtures import BASE_TIME, completed_run, official_policy

from aifreeradar.briefing import render_briefing
from aifreeradar.config import Settings
from aifreeradar.models import Category, LeadDiscovery, ResearchBatch, Scope
from aifreeradar.service import TaskManager
from aifreeradar.storage import Repository

DOCS_URL = "https://fixture-provider.test/docs/api"
SEARCH_QUERY = "fixture text api free"


@pytest.fixture
def repository(tmp_path):
    return Repository(tmp_path / "data")


def _pending(repository, task_id="leads"):
    run = completed_run(task_id)
    repository.save_run(run)
    policy = official_policy(quota="未说明")
    changes = repository.apply_batch(ResearchBatch(resources=[policy]), run, BASE_TIME)
    (resource,) = repository.list_resources()
    return run, resource, changes


def _discovery(**overrides):
    values = {
        "url": DOCS_URL,
        "category": Category.TEXT,
        "source_class": "discovery-only",
        "origin": "search",
        "provider": "Example Search",
        "query": SEARCH_QUERY,
    }
    values.update(overrides)
    return LeadDiscovery(**values)


def test_search_discovery_renders_summary_and_matching_pending_source(repository):
    run, resource, changes = _pending(repository)
    markdown = render_briefing(run, [resource], changes, [], [_discovery()])
    assert "本轮记录发现线索 1 条（官方目录直连 0 / 搜索 1 / 目录链接 0）；仅作线索，不作为官方依据。" in markdown
    assert f"  - 来源：搜索（Example Search）：{SEARCH_QUERY}" in markdown


def test_empty_discoveries_keep_existing_pending_briefing(repository):
    run, resource, changes = _pending(repository)
    markdown = render_briefing(run, [resource], changes, [])
    assert "本轮记录发现线索" not in markdown
    assert "  - 来源：" not in markdown


def test_direct_origin_renders_official_directory_label(repository):
    run, resource, changes = _pending(repository)
    lead = _discovery(origin="direct", provider=None, query=None)
    markdown = render_briefing(run, [resource], changes, [], [lead])
    assert "本轮记录发现线索 1 条（官方目录直连 1 / 搜索 0 / 目录链接 0）；仅作线索，不作为官方依据。" in markdown
    assert "  - 来源：官方目录直连" in markdown


class DiscoveryResearcher:
    def __init__(self, batch, discoveries):
        self.batch = batch
        self.last_discoveries = discoveries

    async def research(self, scope, existing):
        return self.batch.model_copy(deep=True)


@pytest.mark.asyncio
async def test_service_persists_rows_and_briefing_mentions_source(tmp_path):
    settings = Settings(data_dir=tmp_path, schedule_enabled=False)
    repository = Repository(tmp_path)
    researcher = DiscoveryResearcher(
        ResearchBatch(resources=[official_policy(quota="未说明")]),
        [_discovery()],
    )
    manager = TaskManager(settings, repository, researcher)
    try:
        run = await manager.start(Scope(categories=[Category.TEXT]))
        await manager.wait_idle()
    finally:
        await manager.close()

    saved = repository.get_run(run.id)
    assert saved is not None
    assert saved.briefing_path is not None

    rows = repository.discoveries_for_run(run.id)
    assert [(row.category, row.url, row.origin) for row in rows] == [
        (Category.TEXT, DOCS_URL, "search")
    ]

    briefing = Path(saved.briefing_path).read_text(encoding="utf-8")
    assert "  - 来源：搜索（Example Search）：fixture text api free" in briefing