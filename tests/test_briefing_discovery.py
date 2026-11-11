"""Rendered and persisted discovery leads in briefings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from domain_fixtures import BASE_TIME, completed_run, official_policy

from aifreeradar.briefing import markdown_text, render_briefing
from aifreeradar.config import Settings
from aifreeradar.models import (
    UNKNOWN,
    Category,
    LeadDiscovery,
    MessageSource,
    NewsItem,
    ResearchBatch,
    Scope,
)
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


def test_next_collection_does_not_repeat_pending_resource_or_old_policy_change(repository):
    old_run, resource, old_changes = _pending(repository)
    next_run = completed_run("next-collection")
    assert old_run.id != next_run.id
    markdown = render_briefing(next_run, [resource], old_changes, [])
    assert "本次无新增或变化" in markdown
    assert resource.service not in markdown
    assert "待核实线索" not in markdown


# --- Bilingual (zh-first) briefing rendering for collected reports ---

def _news(run, **overrides):
    policy_overrides: dict[str, Any] = {
        "quota": "1000 requests per month",
        "quota_unit": "requests",
        "refresh_cycle": "monthly",
        "rate_limit": "10 requests per minute",
        "claim_conditions": "Free registration and no purchase required",
        "expiry_notes": "No fixed end date",
        "region_restrictions": "Available worldwide",
        "status": "pending",
    }
    policy_overrides.update(overrides.pop("policy", {}))
    values = {
        "policy": official_policy(**policy_overrides),
        "title": "Free Text API tier announced",
        "summary": "Free API tier with 1000 monthly requests and no purchase required",
        "sources": [
            MessageSource(
                url=DOCS_URL,
                title="Fixture official page",
                excerpt="Free tier with 1000 requests per month",
                source_type="official",
                access="page",
            )
        ],
        "resource_id": "fixture-message-resource",
        "task_id": run.id,
        "kind": "new",
        "discovered_at": BASE_TIME,
        "first_seen_at": BASE_TIME,
    }
    values.update(overrides)
    return NewsItem(**values)


def _translated_news(run, **overrides):
    news = _news(
        run,
        ended=True,
        end_reason="Official announcement says the campaign has ended",
        **overrides,
    )
    return news.model_copy(
        update={
            "title_zh": "免费文本接口层级发布",
            "summary_zh": "免费接口层级，每月一千次请求，无需购买",
            "end_reason_zh": "官方公告：活动已结束",
            "policy": news.policy.model_copy(
                update={
                    "quota_zh": "每月一千次请求",
                    "quota_unit_zh": "请求次数",
                    "refresh_cycle_zh": "每月刷新",
                    "rate_limit_zh": "每分钟十次请求",
                    "claim_conditions_zh": "免费注册且无需购买",
                    "expiry_notes_zh": "无固定截止日期",
                    "region_restrictions_zh": "全球可用",
                }
            ),
        }
    )


def test_news_section_is_bilingual_zh_first_with_original_annotation():
    run = completed_run("bilingual-news")
    translated = _translated_news(run)
    chinese = _news(
        run,
        title="免费接口发布",
        summary="免费接口层级，每月一千次请求",
        policy={
            "quota": UNKNOWN,
            "quota_unit": "次",
            "refresh_cycle": "每日 00:00 UTC",
            "rate_limit": UNKNOWN,
            "claim_conditions": "免费注册",
            "expiry_notes": "持续政策",
            "region_restrictions": "支持中国大陆用户",
        },
    )
    markdown = render_briefing(run, [], [], [], messages=[translated, chinese])

    assert "## 消息动态" in markdown
    assert markdown.count("机器翻译，未经核验") == 1
    assert "### 免费文本接口层级发布" in markdown
    assert "> 原文：Free Text API tier announced" in markdown
    assert (
        "- 免费机会：免费接口层级，每月一千次请求，无需购买"
        "（原文：Free API tier with 1000 monthly requests and no purchase required）"
    ) in markdown
    assert (
        "免费额度：每月一千次请求（原文：1000 requests per month） "
        "请求次数（原文：requests）；"
        "刷新周期：每月刷新（原文：monthly）；"
        "限速：每分钟十次请求（原文：10 requests per minute）"
    ) in markdown
    assert (
        "领取条件：免费注册且无需购买（原文：Free registration and no purchase required）"
    ) in markdown
    assert "无固定截止日期（原文：No fixed end date）" in markdown
    assert "全球可用（原文：Available worldwide）" in markdown
    assert (
        "- 结束依据：官方公告：活动已结束（原文：Official announcement says the campaign has ended）"
    ) in markdown
    # Evidence excerpts are never translated or annotated.
    assert "摘录：Free tier with 1000 requests per month" in markdown
    assert "（原文：Free tier" not in markdown
    # Pure-Chinese and placeholder reports stay original-only.
    assert "### 免费接口发布" in markdown
    assert "- 免费机会：免费接口层级，每月一千次请求" in markdown
    assert "免费额度：未说明 次；刷新周期：每日 00:00 UTC；限速：未说明" in markdown


def test_pending_lead_failure_reason_is_bilingual_and_labels_once_per_section(repository):
    run = completed_run("bilingual-lead")
    repository.save_run(run)
    changes = repository.apply_batch(
        ResearchBatch(
            resources=[
                official_policy(
                    quota=UNKNOWN,
                    failure_reason="Official documentation does not state the free quota",
                )
            ]
        ),
        run,
        BASE_TIME,
    )
    (stored,) = repository.list_resources()
    assert stored.status == "pending"
    repository.save_resource_translations(
        [stored.model_copy(update={"failure_reason_zh": "官方文档未说明免费额度"})]
    )
    lead = repository.get_resource(stored.id)
    assert lead is not None
    markdown = render_briefing(run, [lead], changes, [], messages=[_translated_news(run)])

    assert "## 待核实线索" in markdown
    reason = f"{lead.failure_reason_zh}（原文：{lead.failure_reason}）"
    assert f"- {lead.service}：{markdown_text(reason)}；不作为正式推荐。" in markdown
    assert markdown.count("机器翻译，未经核验") == 2
    assert "### 免费文本接口层级发布" in markdown


def test_verified_policy_section_and_evidence_stay_original_even_with_zh(repository):
    run = completed_run("verified-policy")
    repository.save_run(run)
    changes = repository.apply_batch(
        ResearchBatch(
            resources=[
                official_policy(
                    quota="1000 requests per month",
                    quota_unit="requests",
                    refresh_cycle="monthly",
                    claim_conditions="Free registration and no purchase required",
                )
            ]
        ),
        run,
        BASE_TIME,
    )
    (stored,) = repository.list_resources()
    repository.save_resource_translations(
        [
            stored.model_copy(
                update={
                    "quota_zh": "每月一千次请求",
                    "claim_conditions_zh": "免费注册且无需购买",
                    "failure_reason_zh": "机器译文不应出现在已核验段",
                }
            )
        ]
    )
    verified = repository.get_resource(stored.id)
    assert verified is not None
    markdown = render_briefing(run, [verified], changes, [])

    assert "## 新发现 / 首次清单" in markdown
    assert "- 免费额度及刷新周期：1000 requests per month requests；monthly" in markdown
    assert (
        "注册、领取及支付条件：Free registration and no purchase required；必须支付：否"
    ) in markdown
    assert "引文：Fixture official statement for quota: 1000 requests per month" in markdown
    assert "每月一千次请求" not in markdown
    assert "免费注册且无需购买" not in markdown
    assert "机器译文不应出现在已核验段" not in markdown
    assert "（原文：" not in markdown
    assert "机器翻译，未经核验" not in markdown