"""Structured policy records shared by research, persistence, and the local UI."""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

UNKNOWN = "未说明"


def utc_now() -> datetime:
    return datetime.now(UTC)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时间必须包含时区")
    return value.astimezone(UTC)


def normalize_domain(value: str) -> str:
    value = value.strip().lower()
    if value in {"", UNKNOWN, "未核实"}:
        return ""
    parsed = urlsplit(value if "://" in value else f"https://{value}")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("提供商域名无效")
    host = parsed.hostname.rstrip(".").encode("idna").decode("ascii")
    return host.removeprefix("www.")


class Category(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    SPEECH = "speech"
    EMBEDDING = "embedding"
    RERANK = "rerank"


class ResourceStatus(StrEnum):
    ACTIVE = "active"
    PENDING = "pending"
    EXPIRED = "expired"


class CheckStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


class FreeType(StrEnum):
    ONGOING = "ongoing"
    LIMITED = "limited"
    UNKNOWN = "unknown"


class ChinaPolicy(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class ReviewState(StrEnum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    IGNORED = "ignored"


AccessMode = Literal["api", "product", "unknown"]

ReviewAction = Literal[
    "confirm",
    "reject",
    "ignore",
    "reopen",
    "favorite",
    "unfavorite",
    "note",
]


CATEGORY_LABELS = {
    "text": "文本生成",
    "image": "图像",
    "video": "视频",
    "speech": "语音",
    "embedding": "Embedding",
    "rerank": "Rerank",
}
STATUS_LABELS = {"active": "有效", "pending": "待核实", "expired": "已失效"}
CHECK_STATUS_LABELS = {"success": "成功", "failed": "失败", "incomplete": "未完成"}
FREE_TYPE_LABELS = {"ongoing": "持续免费", "limited": "限时免费", "unknown": "待核实"}
CHINA_POLICY_LABELS = {
    "supported": "官方支持中国大陆",
    "unsupported": "不支持",
    "unknown": "未核实",
}

ACCESS_MODE_LABELS = {
    "api": "API 可调用",
    "product": "产品内额度（非 API）",
    "unknown": "入口未核实",
}

REVIEW_STATE_LABELS = {
    "open": "未处理",
    "confirmed": "已确认",
    "rejected": "已驳回",
    "ignored": "已忽略",
}

TRIGGER_LABELS = {"manual": "手动", "scheduled": "定时", "catchup": "补跑"}
RUN_STATUS_LABELS = {
    "running": "运行中",
    "success": "成功",
    "partial": "部分完成",
    "failed": "失败",
}


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Scope(Record):
    categories: list[Category] = Field(default_factory=lambda: list(Category))
    region: Literal["global", "china"] = "global"
    resource_ids: list[str] = Field(default_factory=list)

    @field_validator("categories")
    @classmethod
    def distinct_categories(cls, values: list[Category]) -> list[Category]:
        if not values:
            raise ValueError("研究范围至少包含一个类别")
        return list(dict.fromkeys(values))

    @field_validator("resource_ids")
    @classmethod
    def distinct_resources(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    def includes(self, resource: Policy) -> bool:
        if self.resource_ids:
            # A single-resource recheck addresses records by identity, not by category.
            identifier = getattr(resource, "id", None) or resource.resource_id
            return identifier in self.resource_ids
        # Unknown China policy must still be checked in a China-scoped run.
        return resource.category in self.categories


class Evidence(Record):
    id: str = Field(default_factory=lambda: uuid4().hex)
    field: str
    url: str
    quote: str
    source_type: Literal["official", "community"]
    checked_at: datetime = Field(default_factory=utc_now)
    official_domain: str | None = None

    @field_validator("checked_at")
    @classmethod
    def evidence_time(cls, value: datetime) -> datetime:
        return aware_utc(value)


def _quote_contains(quote: str, value: str) -> bool:
    return " ".join(value.casefold().split()) in " ".join(quote.casefold().split())


class QuotaFact(Record):
    amount: float | None = None
    unit: str = Field(min_length=1, max_length=200)
    period: str = UNKNOWN
    scope: str = "unspecified"
    condition: str = ""
    model_ids: list[str] = Field(default_factory=list)
    source_url: str
    quote: str = Field(min_length=1)
    value_phrase: str = ""

    @field_validator("amount", mode="before")
    @classmethod
    def meaningful_amount(cls, value: object) -> object:
        if value is not None:
            if isinstance(value, bool):
                raise ValueError("额度不能使用布尔值")
            try:
                amount = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError) as error:
                raise ValueError("额度必须是有限非负数字") from error
            if not math.isfinite(amount) or amount < 0:
                raise ValueError("额度必须是有限非负数字")
        return value

    @model_validator(mode="after")
    def supported_value(self) -> QuotaFact:
        MessageSource.safe_url(self.source_url)
        if not self.quote.strip() or not self.unit.strip() or not self.scope.strip():
            raise ValueError("额度单位、作用域和原文不能为空")
        if self.amount is not None:
            numbers = re.findall(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?", self.quote)
            if not any(float(number.replace(",", "")) == self.amount for number in numbers):
                raise ValueError("额度数字缺少原文支持")
        for value in [self.condition, self.value_phrase, *self.model_ids]:
            if value and not _quote_contains(self.quote, value):
                raise ValueError("额度条件、数值表述或模型 ID 缺少原文支持")
        return self


class ModelDeployment(Record):
    provider: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    base_model: str = Field(min_length=1)
    source_url: str
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def explicit_mapping(self) -> ModelDeployment:
        MessageSource.safe_url(self.source_url)
        if not all(
            value.strip() and _quote_contains(self.quote, value)
            for value in (self.provider, self.model_id, self.base_model)
        ):
            raise ValueError("模型部署映射必须在原文中明确提供方、部署 ID 和基础模型")
        return self


class SourceRule(Record):
    id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=128)
    field: Literal["title", "content", "url"]
    pattern: str = Field(min_length=1, max_length=1000)
    action: Literal["tag", "deprioritize", "review"] = "tag"
    label: str = Field(min_length=1, max_length=120)

    @field_validator("id", "label", "pattern")
    @classmethod
    def bounded_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("规则标识、标签和表达式不能为空")
        return value

    @field_validator("pattern")
    @classmethod
    def valid_pattern(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as error:
            raise ValueError(f"无效的正则表达式：{error}") from error
        return value


class RuleMatch(Record):
    rule_id: str
    field: str
    action: str
    label: str


class SourceDefinition(Record):
    id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    url: str
    kind: Literal["web", "feed", "catalog"] = "web"
    categories: list[Category] = Field(default_factory=lambda: list(Category))
    source_type: Literal["official", "community", "github", "catalog"] = "community"
    official_domain: str = ""
    enabled: bool = True
    interval_seconds: int = Field(default=86400, ge=60, le=31536000)
    include_selectors: list[str] = Field(default_factory=list, max_length=100)
    exclude_selectors: list[str] = Field(default_factory=list, max_length=100)
    ignore_patterns: list[str] = Field(default_factory=list, max_length=100)
    rules: list[SourceRule] = Field(default_factory=list, max_length=100)
    checked_on: date | None = None
    review_reason: str = ""
    reopen_if: str = ""

    @field_validator("id", "name")
    @classmethod
    def named_source(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("来源标识和名称不能为空")
        return value.strip()

    @field_validator("url")
    @classmethod
    def public_url(cls, value: str) -> str:
        # Reuse the transport's structural guard; DNS is checked only on actual GET.
        from .research import PublicPageFetcher

        try:
            PublicPageFetcher.validate_url(value.strip())
        except (ValueError, RuntimeError) as error:
            raise ValueError(str(error)) from error
        return value.strip()

    @field_validator("official_domain")
    @classmethod
    def source_domain(cls, value: str) -> str:
        return normalize_domain(value)

    @field_validator("categories")
    @classmethod
    def source_categories(cls, values: list[Category]) -> list[Category]:
        if not values:
            raise ValueError("来源至少包含一个类别")
        return list(dict.fromkeys(values))

    @field_validator("include_selectors", "exclude_selectors")
    @classmethod
    def valid_selectors(cls, values: list[str]) -> list[str]:
        import soupsieve

        for value in values:
            if not value.strip() or len(value) > 500:
                raise ValueError("CSS 选择器不能为空且最多 500 个字符")
            try:
                soupsieve.compile(value)
            except Exception as error:
                raise ValueError(f"无效的 CSS 选择器：{error}") from error
        return values

    @field_validator("ignore_patterns")
    @classmethod
    def valid_noise_patterns(cls, values: list[str]) -> list[str]:
        for value in values:
            if len(value) > 1000:
                raise ValueError("噪声表达式过长")
            try:
                re.compile(value)
            except re.error as error:
                raise ValueError(f"无效的正则表达式：{error}") from error
        return values

    @model_validator(mode="after")
    def unique_rules(self) -> SourceDefinition:
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("同一来源的规则标识必须唯一")
        return self


class SourceState(Record):
    source_id: str
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    status: Literal["never", "ok", "error"] = "never"
    error: str = ""
    etag: str = ""
    last_modified: str = ""
    last_snapshot_id: str | None = None
    config_hash: str = ""
    entry_count: int = 0
    window_oldest: datetime | None = None
    coverage_warning: str = ""
    next_check_at: datetime | None = None

    @field_validator("last_checked_at", "last_success_at", "window_oldest", "next_check_at")
    @classmethod
    def state_time(cls, value: datetime | None) -> datetime | None:
        return aware_utc(value) if value else None


class SourceEntry(Record):
    id: str = Field(default_factory=lambda: uuid4().hex)
    source_id: str
    external_id: str = Field(min_length=1)
    url: str
    title: str = ""
    content: str = ""
    published_at: datetime | None = None
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)
    content_hash: str = ""
    revision: int = Field(default=1, ge=1)
    rule_matches: list[RuleMatch] = Field(default_factory=list)
    priority: int = 0
    needs_review: bool = False
    raw_content: str = ""
    run_id: str = ""

    @field_validator("published_at", "first_seen_at", "last_seen_at")
    @classmethod
    def entry_time(cls, value: datetime | None) -> datetime | None:
        return aware_utc(value) if value else None


class SourceSnapshot(Record):
    id: str = Field(default_factory=lambda: uuid4().hex)
    source_id: str
    url: str
    fetched_at: datetime = Field(default_factory=utc_now)
    raw_content: str
    content_type: str = ""
    text: str
    links: list[str] = Field(default_factory=list)
    raw_hash: str
    normalized_hash: str
    config_hash: str
    previous_id: str | None = None
    text_diff: str = ""
    added_links: list[str] = Field(default_factory=list)
    removed_links: list[str] = Field(default_factory=list)
    run_id: str = ""

    @field_validator("fetched_at")
    @classmethod
    def snapshot_time(cls, value: datetime) -> datetime:
        return aware_utc(value)


class ResearchGap(Record):
    id: str
    category: Category
    query: str
    goal: str
    trigger_url: str
    source_ids: list[str] = Field(default_factory=list)


class ResearchTrace(Record):
    gap_id: str
    category: Category
    query: str
    goal: str
    trigger_url: str
    source_ids: list[str] = Field(default_factory=list)
    result_urls: list[str] = Field(default_factory=list)
    new_evidence_urls: list[str] = Field(default_factory=list)
    stop_reason: Literal[
        "gap_resolved",
        "no_new_evidence",
        "budget_exhausted",
        "provider_failed",
        "duplicate_query",
        "pending",
    ] = "pending"
    search_calls: int = 0
    observed_at: datetime = Field(default_factory=utc_now)

    @field_validator("observed_at")
    @classmethod
    def trace_time(cls, value: datetime) -> datetime:
        return aware_utc(value)


class Policy(Record):
    provider: str
    service: str
    category: Category
    provider_domain: str = ""
    service_key: str = ""
    access_mode: AccessMode = "unknown"
    resource_id: str | None = None
    aliases: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    api_url: str = UNKNOWN
    docs_url: str = UNKNOWN
    free_type: FreeType = FreeType.UNKNOWN
    quota: str = UNKNOWN
    quota_unit: str = UNKNOWN
    refresh_cycle: str = UNKNOWN
    rate_limit: str = UNKNOWN
    claim_conditions: str = UNKNOWN
    payment_required: bool | None = None
    payment_method_required: bool | None = None
    expires_at: datetime | None = None
    expiry_notes: str = UNKNOWN
    region_restrictions: str = UNKNOWN
    china_policy: ChinaPolicy = ChinaPolicy.UNKNOWN
    evidence: list[Evidence] = Field(default_factory=list)
    quota_facts: list[QuotaFact] = Field(default_factory=list)
    model_deployments: list[ModelDeployment] = Field(default_factory=list)
    fact_warnings: list[str] = Field(default_factory=list)
    status: ResourceStatus = ResourceStatus.PENDING
    check_status: CheckStatus = CheckStatus.SUCCESS
    failure_reason: str = ""
    # Additive machine translations (zh). Empty means untranslated; the original
    # field above always stays authoritative for verification and evidence.
    quota_zh: str = ""
    quota_unit_zh: str = ""
    refresh_cycle_zh: str = ""
    rate_limit_zh: str = ""
    claim_conditions_zh: str = ""
    expiry_notes_zh: str = ""
    region_restrictions_zh: str = ""
    failure_reason_zh: str = ""

    @model_validator(mode="before")
    @classmethod
    def optional_facts(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        values = dict(value)
        warnings = list(values.get("fact_warnings") or [])
        labels = {"quota_facts": "额度事实", "model_deployments": "模型部署事实"}
        for field, model in (("quota_facts", QuotaFact), ("model_deployments", ModelDeployment)):
            accepted = []
            raw = values.get(field, [])
            label = labels[field]
            if not isinstance(raw, (list, tuple)):
                warnings.append(f"{label}：可选事实必须为列表，已忽略")
                raw = []
            for index, item in enumerate(raw):
                try:
                    accepted.append(model.model_validate(item))
                except (ValidationError, ValueError, TypeError) as error:
                    warnings.append(
                        f"{label}[{index}]：可选事实缺少有效原文支持，"
                        f"已忽略（{str(error).splitlines()[0]}）"
                    )
            values[field] = accepted
        values["fact_warnings"] = list(dict.fromkeys(warnings))
        return values

    @field_validator("provider", "service")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("提供商和服务名称不能为空")
        return value.strip()

    @field_validator("provider_domain")
    @classmethod
    def canonical_domain(cls, value: str) -> str:
        return normalize_domain(value)

    @field_validator("service_key")
    @classmethod
    def canonical_service_key(cls, value: str) -> str:
        return value.strip().casefold()

    @field_validator("expires_at")
    @classmethod
    def expiry_time(cls, value: datetime | None) -> datetime | None:
        return aware_utc(value) if value else None


class MessageSource(Record):
    url: str
    title: str = ""
    excerpt: str
    source_type: Literal["official", "community", "github", "search", "catalog"] = "search"
    access: Literal["page", "snippet", "feed", "catalog"] = "snippet"
    source_id: str = ""
    external_id: str = ""
    published_at: datetime | None = None

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        value = value.strip()
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or any(ord(char) < 33 for char in value)
            or "\\" in value
        ):
            raise ValueError("消息来源必须是无凭据的 HTTP(S) 链接")
        return value

    @field_validator("excerpt")
    @classmethod
    def nonempty_excerpt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("消息来源摘录不能为空")
        return value.strip()

    @field_validator("published_at")
    @classmethod
    def publication_time(cls, value: datetime | None) -> datetime | None:
        return aware_utc(value) if value else None


class CollectedMessage(Record):
    """A source report, kept separate from officially verified policy facts."""

    policy: Policy
    offer_key: str = "default"
    title: str
    summary: str
    sources: list[MessageSource] = Field(min_length=1)
    published_at: datetime | None = None
    ended: bool = False
    end_reason: str = ""
    # Additive machine translations (zh); original title/summary/end_reason kept.
    title_zh: str = ""
    summary_zh: str = ""
    end_reason_zh: str = ""

    @field_validator("offer_key", "title", "summary")
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("活动标识、标题和免费摘要不能为空")
        return value.strip()

    @field_validator("published_at")
    @classmethod
    def publication_time(cls, value: datetime | None) -> datetime | None:
        return aware_utc(value) if value else None


class NewsItem(CollectedMessage):
    id: str = Field(default_factory=lambda: uuid4().hex)
    resource_id: str
    task_id: str
    kind: Literal["new", "changed", "expired", "restored"]
    discovered_at: datetime = Field(default_factory=utc_now)
    first_seen_at: datetime = Field(default_factory=utc_now)

    @field_validator("discovered_at", "first_seen_at")
    @classmethod
    def event_time(cls, value: datetime) -> datetime:
        return aware_utc(value)


class Resource(Policy):
    id: str = Field(default_factory=lambda: uuid4().hex)
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_checked_at: datetime = Field(default_factory=utc_now)
    last_success_at: datetime | None = None
    last_task_id: str = ""
    recommended_at: datetime | None = None
    messages: list[CollectedMessage] = Field(default_factory=list)

    @field_validator("first_seen_at", "last_checked_at", "last_success_at", "recommended_at")
    @classmethod
    def record_time(cls, value: datetime | None) -> datetime | None:
        return aware_utc(value) if value else None


class ResourceReview(Record):
    """Human judgment kept apart from researched evidence."""

    resource_id: str
    state: ReviewState = ReviewState.OPEN
    favorite: bool = False
    note: str = ""
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("note")
    @classmethod
    def bounded_note(cls, value: str) -> str:
        text = value.strip()
        if len(text) > 2000:
            raise ValueError("备注最多 2000 个字符")
        return text

    @field_validator("updated_at")
    @classmethod
    def review_time(cls, value: datetime) -> datetime:
        return aware_utc(value)


class UserAction(Record):
    id: str = Field(default_factory=lambda: uuid4().hex)
    resource_id: str
    action: ReviewAction
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def action_time(cls, value: datetime) -> datetime:
        return aware_utc(value)


class ResearchBatch(Record):
    resources: list[Policy] = Field(default_factory=list)
    messages: list[CollectedMessage] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    memory_notes: str = ""
    research_traces: list[ResearchTrace] = Field(default_factory=list)


class Change(Record):
    id: str = Field(default_factory=lambda: uuid4().hex)
    resource_id: str
    task_id: str
    kind: Literal["new", "changed", "expired", "restored"]
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    discovered_at: datetime = Field(default_factory=utc_now)

    @field_validator("discovered_at")
    @classmethod
    def discovery_time(cls, value: datetime) -> datetime:
        return aware_utc(value)


LeadSourceClass = Literal["official-verifiable", "discovery-only"]
LeadOrigin = Literal["direct", "link", "search", "feed", "catalog"]


class LeadDiscovery(Record):
    """A lead surfaced by research, kept apart from human-approved resources."""

    url: str
    category: Category
    source_class: LeadSourceClass
    origin: LeadOrigin
    provider: str | None = None
    query: str | None = None
    discovered_at: datetime = Field(default_factory=utc_now)

    @field_validator("discovered_at")
    @classmethod
    def lead_discovery_time(cls, value: datetime) -> datetime:
        return aware_utc(value)


class RunStats(Record):
    search_calls: int = 0
    fetch_calls: int = 0
    model_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0


class Run(Record):
    id: str = Field(default_factory=lambda: uuid4().hex)
    trigger: Literal["manual", "scheduled", "catchup"] = "manual"
    scope: Scope = Field(default_factory=Scope)
    status: Literal["running", "success", "partial", "failed"] = "running"
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    error: str = ""
    notes: list[str] = Field(default_factory=list)
    briefing_path: str | None = None
    schedule_day: str | None = None
    stats: RunStats | None = None
    research_traces: list[ResearchTrace] = Field(default_factory=list)

    @field_validator("started_at", "finished_at")
    @classmethod
    def run_time(cls, value: datetime | None) -> datetime | None:
        return aware_utc(value) if value else None

    @field_validator("schedule_day")
    @classmethod
    def schedule_date(cls, value: str | None) -> str | None:
        if value is not None:
            from datetime import date

            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("调度日期必须使用 YYYY-MM-DD")
        return value


def eligible_recommendation(resource: Policy, scope: Scope | None = None) -> bool:
    return (
        resource.status == ResourceStatus.ACTIVE
        and resource.check_status == CheckStatus.SUCCESS
        and resource.payment_required is False
        and resource.payment_method_required is not None
        and (scope is None or scope.includes(resource))
        and (
            scope is None
            or scope.region != "china"
            or resource.china_policy == ChinaPolicy.SUPPORTED
        )
    )
