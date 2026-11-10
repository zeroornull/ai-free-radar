"""Render a safe, source-linked incremental Markdown briefing."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime
from html import escape
from urllib.parse import quote, urlsplit

from .models import (
    CATEGORY_LABELS,
    CHINA_POLICY_LABELS,
    FREE_TYPE_LABELS,
    RUN_STATUS_LABELS,
    STATUS_LABELS,
    TRIGGER_LABELS,
    UNKNOWN,
    Change,
    CheckStatus,
    LeadDiscovery,
    Resource,
    ResourceStatus,
    Run,
    eligible_recommendation,
)
from .storage import IMPORTANT_FIELDS

FIELD_LABELS = {
    "category": "类别",
    "models": "可用模型",
    "free_type": "免费形式",
    "quota": "免费额度",
    "quota_unit": "额度单位",
    "refresh_cycle": "刷新周期",
    "rate_limit": "限速",
    "claim_conditions": "领取条件",
    "payment_required": "必须支付",
    "payment_method_required": "必须绑定支付方式",
    "expires_at": "到期时间",
    "expiry_notes": "有效期说明",
    "region_restrictions": "地区限制",
    "china_policy": "中国大陆政策",
    "status": "资源状态",
    "api_url": "API 入口",
    "docs_url": "API 文档",
}


def markdown_text(value: object) -> str:
    """One untrusted inline value can never create a heading, HTML, or a link."""
    text = " ".join(str(value).split())
    text = escape(text, quote=True)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~\-])", r"\\\1", text)


def markdown_link(label: str, url: str) -> str:
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not any(ord(char) < 32 or ord(char) == 127 for char in url)
        )
    except ValueError:
        valid = False
    if not valid:
        return f"{markdown_text(label)}：{markdown_text(url)}"
    destination = quote(url, safe="/:?#=@!$&'*,;+%~-_")
    return f"[{markdown_text(label)}](<{destination}>)"


def _time(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") if value else "无成功核查记录"


def _display(value: object, field: str = "") -> str:
    if value is None:
        return "未核实"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, list):
        return "、".join(str(item) for item in value) or UNKNOWN
    mapping = {
        "status": STATUS_LABELS,
        "free_type": FREE_TYPE_LABELS,
        "china_policy": CHINA_POLICY_LABELS,
        "category": CATEGORY_LABELS,
    }.get(field, {})
    if isinstance(value, (str, int, float)):
        return mapping.get(str(value), str(value))
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _sources(resource: Resource, official_only: bool = False) -> list[str]:
    lines: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for evidence in resource.evidence:
        if official_only and evidence.source_type != "official":
            continue
        key = (evidence.field, evidence.url, evidence.quote)
        if key in seen:
            continue
        seen.add(key)
        source_type = "官方" if evidence.source_type == "official" else "社区线索（非官方依据）"
        field = FIELD_LABELS.get(evidence.field, evidence.field)
        lines.append(
            f"  - {markdown_text(field)}：{markdown_link(source_type, evidence.url)}；"
            f"引文：{markdown_text(evidence.quote)}；核查时间：{markdown_text(_time(evidence.checked_at))}"
        )
    return lines


def _resource_details(resource: Resource) -> list[str]:
    payment = (
        f"{resource.claim_conditions}；必须支付：{_display(resource.payment_required)}；"
        f"必须绑定支付方式：{_display(resource.payment_method_required)}"
    )
    expiry = (
        f"{_time(resource.expires_at) if resource.expires_at else UNKNOWN}；{resource.expiry_notes}"
    )
    return [
        f"### {markdown_text(resource.service)}",
        "",
        f"- 提供商与类别：{markdown_text(resource.provider)} / {CATEGORY_LABELS[resource.category]}",
        f"- 可用模型：{markdown_text(_display(resource.models))}",
        f"- 免费形式：{FREE_TYPE_LABELS[resource.free_type]}",
        f"- 免费额度及刷新周期：{markdown_text(resource.quota)} {markdown_text(resource.quota_unit)}；{markdown_text(resource.refresh_cycle)}",
        f"- 限速：{markdown_text(resource.rate_limit)}",
        f"- 注册、领取及支付条件：{markdown_text(payment)}",
        f"- 有效期：{markdown_text(expiry)}",
        f"- 地区政策：{CHINA_POLICY_LABELS[resource.china_policy]}；{markdown_text(resource.region_restrictions)}；网络访问未实测",
        f"- 使用入口及 API 文档：{markdown_link('API 入口', resource.api_url)}；{markdown_link('API 文档', resource.docs_url)}",
        "- 官方依据：",
        *_sources(resource, official_only=True),
        f"- 核查时间：{markdown_text(_time(resource.last_success_at))}；未实测调用",
        f"- 资源状态：{STATUS_LABELS[resource.status]}（官方公开政策核查）",
        "",
    ]


def _changed_values(change: Change) -> list[str]:
    items: list[str] = []
    for field in IMPORTANT_FIELDS:
        before, after = change.before.get(field), change.after.get(field)
        if (
            field == "models"
            and isinstance(before, list)
            and isinstance(after, list)
            and set(before) == set(after)
        ):
            continue
        if before != after:
            items.append(
                f"{FIELD_LABELS.get(field, field)}：{_display(before, field)} → {_display(after, field)}"
            )
    return items



def _stats_line(run: Run) -> str:
    stats = run.stats
    if stats is None:
        return "- 本次消耗：未记录"
    return (
        f"- 本次消耗：搜索 {stats.search_calls} 次、抓取 {stats.fetch_calls} 页、"
        f"模型请求 {stats.model_requests} 次、输入 {stats.input_tokens} tokens、"
        f"输出 {stats.output_tokens} tokens、缓存命中 {stats.cache_read_tokens} tokens"
    )


def _discovery_label(discovery: LeadDiscovery) -> str:
    if discovery.origin == "direct":
        return "官方目录直连"
    if discovery.origin == "search":
        provider = markdown_text(discovery.provider or "")
        query = markdown_text(discovery.query or "")
        return f"搜索（{provider}）：{query}"
    return "目录链接"


def render_briefing(
    run: Run,
    resources: list[Resource],
    changes: list[Change],
    failures: list[str],
    discoveries: Sequence[LeadDiscovery] = (),
) -> str:
    local_time = run.started_at.astimezone()
    categories = "、".join(CATEGORY_LABELS[item] for item in run.scope.categories)
    region = "全球" if run.scope.region == "global" else "官方支持中国大陆（含待核实线索）"
    lines = [
        f"# 免费 AI API 简报 — {local_time:%Y-%m-%d %H:%M}",
        "",
        f"- 任务：{markdown_text(run.id)}",
        f"- 研究范围：{categories}；{region}",
        f"- 触发方式：{TRIGGER_LABELS[run.trigger]}",
        f"- 执行结果：{RUN_STATUS_LABELS[run.status]}",
        "- 说明：官方政策核查，未实测调用；网络访问未实测；不保证搜索穷尽或政策持续不变。",
        _stats_line(run),
        "",
    ]
    # Combine multiple observations of the same resource into one incremental row.
    grouped: dict[str, Change] = {}
    for change in changes:
        if change.task_id != run.id:
            continue
        if change.resource_id in grouped:
            first = grouped[change.resource_id]
            if first.kind == "new":
                kind = "expired" if change.after.get("status") == "expired" else "new"
            elif change.after.get("status") == "expired":
                kind = "expired"
            elif first.before.get("status") == "expired" and change.after.get("status") == "active":
                kind = "restored"
            else:
                kind = "changed"
            grouped[change.resource_id] = change.model_copy(
                update={"before": first.before, "kind": kind}
            )
        else:
            grouped[change.resource_id] = change
    current = {resource.id: resource for resource in resources if run.scope.includes(resource)}
    observed: dict[str, Resource] = dict(current)
    for identity, change in grouped.items():
        if identity not in observed:
            resource = Resource.model_validate(change.after)
            if run.scope.includes(resource):
                observed[identity] = resource

    fresh: list[Resource] = []
    important: list[tuple[Resource, Change]] = []
    expired: list[tuple[Resource, Change]] = []
    pending: dict[str, Resource] = {}
    unsuccessful: dict[str, Resource] = {}
    for identity, resource in observed.items():
        change = grouped.get(identity)
        touched = resource.last_task_id == run.id or change is not None
        if not touched:
            continue
        if resource.check_status != CheckStatus.SUCCESS:
            unsuccessful[identity] = resource
        if resource.status == ResourceStatus.PENDING or (
            run.scope.region == "china" and resource.china_policy == "unknown"
        ):
            pending[identity] = resource
        if not change:
            continue
        if change.kind == "expired" and resource.status == ResourceStatus.EXPIRED:
            expired.append((resource, change))
        elif eligible_recommendation(resource, run.scope):
            if change.kind == "new":
                fresh.append(resource)
            elif change.kind in {"changed", "restored"}:
                important.append((resource, change))

    if not grouped:
        lines.extend(["本次无新增或变化", ""])
    elif not (fresh or important or expired):
        lines.extend(["本次无符合正式推荐条件的新增或变化；待核实线索及未完成事项见下文。", ""])

    lines.extend(["## 新发现 / 首次清单", ""])
    if fresh:
        for resource in fresh:
            lines.extend(_resource_details(resource))
    else:
        lines.extend(["无。", ""])

    lines.extend(["## 重要变化 / 恢复", ""])
    if important:
        for resource, change in important:
            restoration = "恢复；" if change.kind == "restored" else ""
            differences = "；".join(_changed_values(change)) or "首次符合本次范围的正式推荐条件"
            lines.extend(
                [
                    f"- {markdown_text(resource.service)}：{restoration}{markdown_text(differences)}；核查时间：{markdown_text(_time(resource.last_success_at))}；未实测调用",
                    *_sources(resource, official_only=True),
                    "",
                ]
            )
            lines.extend(_resource_details(resource))
    else:
        lines.extend(["无。", ""])

    lines.extend(["## 已失效", ""])
    if expired:
        for resource, change in expired:
            basis = resource.expiry_notes
            if resource.expires_at:
                basis = f"已确认到期时间：{_time(resource.expires_at)}；{basis}"
            lines.extend(
                [
                    f"- {markdown_text(resource.service)}：{markdown_text(basis)}；核查时间：{markdown_text(_time(resource.last_success_at))}",
                    *_sources(resource, official_only=True),
                    "",
                ]
            )
    else:
        lines.extend(["无。", ""])

    lines.extend(["## 待核实线索", ""])
    if discoveries:
        direct = sum(1 for item in discoveries if item.origin == "direct")
        search = sum(1 for item in discoveries if item.origin == "search")
        link = len(discoveries) - direct - search
        lines.extend(
            [
                (
                    f"本轮记录发现线索 {len(discoveries)} 条"
                    f"（官方目录直连 {direct} / 搜索 {search} / 目录链接 {link}）；"
                    "仅作线索，不作为官方依据。"
                ),
                "",
            ]
        )
    if pending:
        for resource in pending.values():
            reason = resource.failure_reason or "关键免费条件或对应官方依据未明确"
            if run.scope.region == "china" and resource.china_policy == "unknown":
                reason = f"中国大陆注册及 API 使用政策缺少明确官方地区依据；{reason}"
            lines.extend(
                [
                    f"- {markdown_text(resource.service)}：{markdown_text(reason)}；不作为正式推荐。",
                    f"  - 线索入口：{markdown_link('API 入口', resource.api_url)}；{markdown_link('API 文档', resource.docs_url)}",
                    *_sources(resource),
                ]
            )
            lead = next(
                (
                    item
                    for item in discoveries
                    if item.url in {resource.docs_url, resource.api_url}
                ),
                None,
            )
            if lead is not None:
                lines.append(f"  - 来源：{_discovery_label(lead)}")
            lines.append("")
    else:
        lines.extend(["无。", ""])

    lines.extend(["## 核查失败 / 未完成事项", ""])
    issues = list(dict.fromkeys([*failures, *run.notes, *([run.error] if run.error else [])]))
    for resource in unsuccessful.values():
        lines.append(
            f"- {markdown_text(resource.service)}：{markdown_text(resource.failure_reason or '本次核查未完成')}；"
            f"上次已确认结论：{STATUS_LABELS[resource.status]}，"
            f"{FREE_TYPE_LABELS[resource.free_type]}，额度 {markdown_text(resource.quota)} {markdown_text(resource.quota_unit)}，"
            f"刷新周期 {markdown_text(resource.refresh_cycle)}，中国大陆政策 {CHINA_POLICY_LABELS[resource.china_policy]}；"
            f"上次成功核查时间：{markdown_text(_time(resource.last_success_at))}；"
            "结论未获本次更新，未实测调用；网络访问未实测。"
        )
        lines.extend(_sources(resource))
    lines.extend(f"- {markdown_text(issue)}" for issue in issues)
    if not unsuccessful and not issues:
        if run.status in {"partial", "failed", "running"}:
            lines.append("任务尚未全部完成；没有可确认的进一步结果，详见任务执行状态。")
        else:
            lines.append("无。")
    lines.append("")
    return "\n".join(lines)
