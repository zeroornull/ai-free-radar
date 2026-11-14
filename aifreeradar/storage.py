"""SQLite business records; research memory is deliberately not an identity database."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .legacy_sources import cached_sources, matching_sources, safe_source
from .models import (
    UNKNOWN,
    Category,
    Change,
    CheckStatus,
    ChinaPolicy,
    CollectedMessage,
    Evidence,
    FreeType,
    LeadDiscovery,
    MessageSource,
    ModelDeployment,
    NewsItem,
    Policy,
    QuotaFact,
    ResearchBatch,
    Resource,
    ResourceReview,
    ResourceStatus,
    ReviewAction,
    ReviewState,
    Run,
    SourceDefinition,
    SourceEntry,
    SourceSnapshot,
    SourceState,
    UserAction,
    aware_utc,
    eligible_recommendation,
    normalize_domain,
    utc_now,
)

# These are facts, rather than presentation, identity labels, or observation times.
IMPORTANT_FIELDS = (
    "access_mode",
    "category",
    "models",
    "free_type",
    "quota",
    "quota_unit",
    "refresh_cycle",
    "rate_limit",
    "claim_conditions",
    "payment_required",
    "payment_method_required",
    "expires_at",
    "expiry_notes",
    "region_restrictions",
    "china_policy",
    "status",
)


def _known(value: str) -> bool:
    return bool(value.strip()) and value.strip() not in {UNKNOWN, "未核实", "未知", "unknown"}


def _token(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _service_tokens(policy: Policy) -> set[str]:
    # Entry URLs are often shared across different APIs. They never identify a service.
    return {
        _token(value)
        for value in [policy.service_key, policy.service, *policy.aliases]
        if value and "://" not in value and _token(value)
    }


def _same_service(left: Policy, right: Policy) -> bool:
    if left.service_key and right.service_key:
        if left.service_key == right.service_key:
            return True
        # Distinct stable keys do not merge merely because both display names
        # happen to be "API". A rename must explicitly carry an old alias.
        left_aliases = {_token(value) for value in left.aliases if "://" not in value}
        right_aliases = {_token(value) for value in right.aliases if "://" not in value}
        key_alias = (
            _token(right.service_key) in left_aliases or _token(left.service_key) in right_aliases
        )
        renamed_alias = _token(left.service) != _token(right.service) and (
            _token(right.service) in left_aliases or _token(left.service) in right_aliases
        )
        return key_alias or renamed_alias
    return bool(_service_tokens(left) & _service_tokens(right))


def _official(evidence: Evidence, domain: str, now: datetime) -> bool:
    if evidence.source_type != "official" or not domain or not evidence.quote.strip():
        return False
    try:
        parsed = urlsplit(evidence.url)
        host = normalize_domain(parsed.hostname or "")
        declared = normalize_domain(evidence.official_domain or domain)
        return (
            parsed.scheme in {"http", "https"}
            and not parsed.username
            and not parsed.password
            and bool(host)
            and (host == domain or host.endswith(f".{domain}"))
            and (declared == domain or declared.endswith(f".{domain}"))
            and (host == declared or host.endswith(f".{declared}"))
            and evidence.checked_at <= now
        )
    except (ValueError, UnicodeError):
        return False


def validate_policy(policy: Policy, now: datetime) -> Policy:
    """Enforce official, field-specific policy evidence independently of model judgment.

    Retrieval/quotation provenance is checked by the research adapter. This boundary
    also checks URL ownership, so a self-declared official_domain cannot bless an
    unrelated community URL.
    """
    now = aware_utc(now)
    result = policy.model_copy(deep=True)
    result.evidence = [
        item
        for item in result.evidence
        if item.source_type == "community" or _official(item, result.provider_domain, now)
    ]
    official_fields = {
        item.field.strip()
        for item in result.evidence
        if _official(item, result.provider_domain, now)
    }
    problems: list[str] = []
    if not result.provider_domain:
        problems.append("缺少提供商官方域名")
    if result.china_policy != ChinaPolicy.UNKNOWN and not (
        {"china_policy", "region_restrictions"} & official_fields
    ):
        result.china_policy = ChinaPolicy.UNKNOWN
        problems.append("中国大陆政策缺少官方地区依据")

    # Only a confirmed expiry or explicit official shutdown can establish expiry.
    confirmed_expiry = (
        result.expires_at is not None
        and "expires_at" in official_fields
        and result.expires_at <= now
    )
    confirmed_shutdown = result.status == ResourceStatus.EXPIRED and "status" in official_fields
    if confirmed_expiry or confirmed_shutdown:
        result.status = ResourceStatus.EXPIRED
        result.failure_reason = "; ".join(filter(None, [result.failure_reason, *problems]))
        return result

    if result.status == ResourceStatus.EXPIRED:
        problems.append("失效结论缺少官方依据或已确认到期事实")
    required = {
        "free_type",
        "quota",
        "quota_unit",
        "claim_conditions",
        "payment_required",
        "payment_method_required",
    }
    if result.access_mode == "product":
        if not official_fields:
            problems.append("缺少产品页面官方依据")
    elif not ({"api_url", "docs_url"} & official_fields) or not any(
        _known(value) and _valid_http(value) for value in [result.api_url, result.docs_url]
    ):
        problems.append("缺少可接入 API 的官方入口或文档依据")
    if result.free_type == FreeType.ONGOING:
        required.add("refresh_cycle")
        if not _known(result.refresh_cycle):
            problems.append("刷新周期未说明")
    elif result.free_type == FreeType.LIMITED:
        absolute_expiry = result.expires_at is not None and "expires_at" in official_fields
        stated_expiry = _known(result.expiry_notes) and "expiry_notes" in official_fields
        if not (absolute_expiry or stated_expiry):
            problems.append("限时免费有效期未明确核实")
    else:
        problems.append("免费形式未核实")
    for field in ("quota", "quota_unit", "claim_conditions"):
        if not _known(getattr(result, field)):
            problems.append(f"{field} 未说明")
    if result.payment_required is not False:
        problems.append("payment_required 为必须或未核实，未达到免费门槛")
    if result.payment_method_required is None:
        problems.append("payment_method_required 未核实")
    if result.models:
        required.add("models")
    if _known(result.rate_limit):
        required.add("rate_limit")
    if _known(result.region_restrictions):
        required.add("region_restrictions")
    if result.expires_at is not None:
        required.add("expires_at")
    if _known(result.expiry_notes):
        required.add("expiry_notes")
    missing = sorted(required - official_fields)
    if missing:
        problems.append("缺少字段对应官方依据：" + "、".join(missing))
    if result.failure_reason.strip():
        problems.insert(0, result.failure_reason.strip())
    result.failure_reason = "; ".join(dict.fromkeys(problems))
    result.status = ResourceStatus.PENDING if problems else ResourceStatus.ACTIVE
    return result


def _valid_http(value: str) -> bool:
    try:
        url = urlsplit(value)
        return (
            url.scheme in {"http", "https"}
            and bool(url.hostname)
            and not url.username
            and not url.password
        )
    except ValueError:
        return False


_FREE = re.compile(
    r"\bfree\b|\bno charge\b|\bno cost\b|免费|赠送|赠额|零费用|零支付"
    r"|\b(?:welcome|sign[ -]?up|monthly|bonus|complimentary|trial)\s+credits?\b"
    r"|免费积分|免费额度|免费试用|免费体验",
    re.IGNORECASE,
)
_API = re.compile(r"\bapi\b|\bsdk\b|接口", re.IGNORECASE)
_PAID = re.compile(
    r"(?:must|required?\s+to|need\s+to)\s+(?:pay|purchase|buy|top[ -]?up|recharge)"
    r"|(?:payment|purchase|top[ -]?up|recharge)\s+(?:is\s+)?required"
    r"|(?:需|须|先|要求|必须)(?:要|先|进行)?(?:付费|付款|支付|购买|充值)"
    r"|(?:付费|付款|充值)(?:才|后|前提).{0,6}?(?:能|可|才|使用|调用|获得)"
    r"|(?:requires?|required?\s+to\s+(?:pay|place))\s+(?:a\s+)?(?:deposit|prepayment)"
    r"|(?:deposit|prepayment)\s+(?:is\s+)?required"
    r"|(?:需|须|要求|必须)(?:先|要|缴纳|支付)?(?:押金|保证金|预存|预充值)",
    re.IGNORECASE,
)
_WEB_ONLY = re.compile(
    r"(?:web|browser|chat)[ -]?only|no\s+api|api\s+(?:is\s+)?(?:not available|unavailable)"
    r"|only\s+available\s+in\s+(?:the\s+)?(?:web|browser)"
    r"|仅(?:限)?网页|仅(?:限)?聊天|不提供\s*API|无\s*API",
    re.IGNORECASE,
)
_NOT_FREE = re.compile(
    r"\b(?:not free|no free|paid only)\b|不免费|没有免费|付费(?:才能|后才)",
    re.IGNORECASE,
)
_REOPENED = re.compile(
    r"\b(?:restored|reopened|renewed|extended|available again|resumed)\b"
    r"|恢复|重新开放|续期|延期|重新上架",
    re.IGNORECASE,
)
MESSAGE_FACT_FIELDS = (
    "access_mode",
    "free_type", "quota", "quota_unit", "refresh_cycle", "rate_limit",
    "claim_conditions", "payment_required", "payment_method_required",
    "expires_at", "expiry_notes", "region_restrictions", "china_policy", "models",
)
MESSAGE_BENEFIT_FIELDS = (
    "quota", "quota_unit", "models", "refresh_cycle", "rate_limit", "claim_conditions",
)

# Additive machine-translation fields; never part of MESSAGE_FACT_FIELDS or
# change detection. Empty means untranslated.
MESSAGE_ZH_FIELDS = tuple(name for name in CollectedMessage.model_fields if name.endswith("_zh"))
POLICY_ZH_FIELDS = tuple(name for name in Policy.model_fields if name.endswith("_zh"))


def _strip_negations(text: str) -> str:
    """Remove no-payment phrasing and card-binding requirements before paid checks."""
    return re.sub(
        r"\b(?:no|without)\s+(?:payment|purchase|top[ -]?up|recharge|deposit|prepayment)"
        r"(?:\s+required)?"
        r"|(?:无需|不需要|不必|不用)(?:付费|付款|支付|购买|充值|押金|保证金|预存|预充值"
        r"|绑定(?:银行卡|信用卡|支付方式))"
        r"|(?:do(?:es)?\s+not|don't|doesn't)\s+(?:need\s+to|require)\s+"
        r"(?:pay|payment|purchase|top[ -]?up|recharge)"
        r"|(?:valid\s+)?payment\s+method\s+(?:is\s+)?required"
        r"|\b402\s+payment\s+required\b"
        r"|(?:require[sd]?\s+(?:a\s+)?valid\s+payment\s+method)"
        r"|(?:须|需|要|必须)(?:绑定|添加|开通)(?:银行卡|信用卡|支付方式|付款方式)",
        " ", text, flags=re.IGNORECASE,
    )


def message_problem(message: CollectedMessage) -> str:
    """Collection boundary for two separate, explicitly labeled access tracks.

    API track (``access_mode`` ``api`` or legacy ``unknown``): the source must
    state a free API/SDK opportunity, and web-only wording still disqualifies it.
    Product track (``product``): the source must state a free in-product credit,
    trial, or quota; a web/desktop/agent entry is expected, so API evidence is
    not required and web-only wording is not a rejection reason. In both tracks
    a stated purchase, top-up, or deposit still disqualifies the message.
    """
    policy = message.policy
    source_texts = [f"{item.title}\n{item.excerpt}" for item in message.sources]
    excerpts = "\n".join(item.excerpt for item in message.sources)
    text = "\n".join(source_texts)
    free_ok = any(_FREE.search(source) for source in source_texts)
    product = policy.access_mode == "product"
    if not free_ok:
        return "来源未明确说明免费机会" if product else "来源未明确说明免费 API 机会"
    if not product:
        api_ok = (
            any(_API.search(source) for source in source_texts)
            or bool(_API.search(policy.service))
            or _valid_http(policy.api_url)
            or _valid_http(policy.docs_url)
        )
        if not api_ok:
            return "来源未明确说明免费 API 机会"
    if policy.payment_required is True:
        return "来源说明需实际付款、购买或充值，非免费机会"
    if _PAID.search(_strip_negations(text)):
        return "来源说明需实际付款、购买或充值，非免费机会"
    if _NOT_FREE.search(excerpts):
        if product:
            return "来源说明已不免费或需付费，非免费产品额度"
        return "来源仅提供网页工具或需付费，未提供免费 API"
    if not product and _WEB_ONLY.search(excerpts):
        return "来源仅提供网页工具或需付费，未提供免费 API"
    return ""


def _legacy_summary(resource: Resource) -> str:
    parts = []
    if _known(resource.quota):
        unit = f" {resource.quota_unit}" if _known(resource.quota_unit) else ""
        parts.append(f"额度 {resource.quota}{unit}")
    if _known(resource.refresh_cycle):
        parts.append(resource.refresh_cycle)
    if _known(resource.claim_conditions):
        parts.append(resource.claim_conditions)
    prefix = "历史来源记录"
    return prefix + "：" + "；".join(parts) if parts else prefix + "，具体条件未说明"


def _sourced_expiry(message: CollectedMessage) -> bool:
    expiry = message.policy.expires_at
    if expiry is None:
        return False
    text = " ".join(item.excerpt for item in message.sources)
    dates = (
        expiry.date().isoformat(),
        f"{expiry.year}/{expiry.month}/{expiry.day}",
        f"{expiry.year}年{expiry.month}月{expiry.day}日",
        expiry.strftime("%B %d, %Y"),
        expiry.strftime("%b %d, %Y"),
    )
    return any(date.casefold() in text.casefold() for date in dates)


def _merge_sources(left: list[MessageSource], right: list[MessageSource]) -> list[MessageSource]:
    merged = list(left)
    keys = {
        (
            item.url,
            item.source_type,
            item.access,
            item.source_id,
            item.external_id,
            " ".join(item.excerpt.split()),
        )
        for item in merged
    }
    for item in right:
        key = (
            item.url,
            item.source_type,
            item.access,
            item.source_id,
            item.external_id,
            " ".join(item.excerpt.split()),
        )
        if key not in keys:
            merged.append(item)
            keys.add(key)
    return merged


def _merge_report(previous: CollectedMessage, incoming: CollectedMessage) -> CollectedMessage:
    """Fill unknown incoming values with previously reported known details."""
    values = incoming.policy.model_dump()
    for field, old in previous.policy.model_dump().items():
        if field in {"quota_facts", "model_deployments", "fact_warnings"}:
            continue
        value = values[field]
        if value is None or value == [] or (isinstance(value, str) and not _known(value)):
            values[field] = old
    # Structured facts are explicit evidence. An absent optional fact means
    # "not observed this time", never that a previously known fact disappeared.
    if not values["quota_facts"]:
        values["quota_facts"] = [fact.model_dump() for fact in previous.policy.quota_facts]
    if not values["model_deployments"]:
        values["model_deployments"] = [
            mapping.model_dump() for mapping in previous.policy.model_deployments
        ]
    return incoming.model_copy(deep=True, update={
        "policy": Policy.model_validate(values),
        "published_at": incoming.published_at or previous.published_at,
    })


def _reported_value(field: str, value: Any) -> Any:
    if field == "models":
        items = sorted({str(item).strip() for item in value if str(item).strip()})
        return items or None
    if isinstance(value, str):
        return value.strip() if _known(value) else None
    return value


def _message_facts(message: CollectedMessage) -> dict:
    data = message.policy.model_dump(mode="json")
    facts = {field: _reported_value(field, data[field]) for field in MESSAGE_FACT_FIELDS}
    facts["ended"] = bool(message.ended)
    facts["quota_facts"] = _quota_signature(message.policy.quota_facts)
    facts["model_deployments"] = _deployment_signature(message.policy.model_deployments)
    if not any(facts[field] not in (None, []) for field in MESSAGE_BENEFIT_FIELDS):
        facts["summary"] = " ".join(message.summary.split()).casefold()
    return facts


def _normal_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _quota_signature(facts: Iterable[QuotaFact]) -> tuple[tuple[object, ...], ...]:
    """Order-independent evidence identity; a display reorder is not a change."""
    return tuple(
        sorted(
            {
                (
                    fact.amount is not None,
                    fact.amount if fact.amount is not None else 0.0,
                    _normal_text(fact.unit),
                    _normal_text(fact.period) or _normal_text(UNKNOWN),
                    _normal_text(fact.scope) or "unspecified",
                    _normal_text(fact.condition),
                    tuple(sorted({_normal_text(item) for item in fact.model_ids if item.strip()})),
                    fact.source_url,
                    _normal_text(fact.quote),
                    _normal_text(fact.value_phrase),
                )
                for fact in facts
            }
        )
    )


def _deployment_signature(
    mappings: Iterable[ModelDeployment],
) -> tuple[tuple[str, ...], ...]:
    return tuple(
        sorted(
            {
                (
                    _normal_text(mapping.provider),
                    mapping.model_id.casefold(),
                    mapping.base_model.casefold(),
                    mapping.source_url,
                    _normal_text(mapping.quote),
                )
                for mapping in mappings
            }
        )
    )


def _facts(resource: Policy) -> dict:
    data = resource.model_dump(mode="json")
    facts = {
        key: sorted(set(data[key])) if key == "models" else data[key] for key in IMPORTANT_FIELDS
    }
    facts["quota_facts"] = _quota_signature(resource.quota_facts)
    facts["model_deployments"] = _deployment_signature(resource.model_deployments)
    return facts


def _snapshot(resource: Resource) -> dict:
    return resource.model_dump(mode="json")


MIGRATIONS = (
    """
    CREATE TABLE IF NOT EXISTS resources (
        id TEXT PRIMARY KEY,
        provider_domain TEXT NOT NULL,
        service_key TEXT NOT NULL,
        category TEXT NOT NULL,
        status TEXT NOT NULL,
        china_policy TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS resources_identity
        ON resources(provider_domain, service_key);
    CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS changes (
        id TEXT PRIMARY KEY,
        resource_id TEXT NOT NULL REFERENCES resources(id),
        task_id TEXT NOT NULL,
        discovered_at TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS changes_resource ON changes(resource_id, discovered_at);
    CREATE INDEX IF NOT EXISTS changes_task ON changes(task_id, discovered_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_reviews (
        resource_id TEXT PRIMARY KEY REFERENCES resources(id),
        state TEXT NOT NULL,
        favorite INTEGER NOT NULL,
        note TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS user_actions (
        id TEXT PRIMARY KEY,
        resource_id TEXT NOT NULL,
        action TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS user_actions_resource
        ON user_actions(resource_id, created_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS settings_secrets (
        name TEXT PRIMARY KEY,
        ciphertext TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS settings_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    INSERT OR IGNORE INTO settings_meta(key, value) VALUES ('config_version', '0');
    """,
    """
    CREATE TABLE IF NOT EXISTS lead_discoveries (
        run_id TEXT NOT NULL,
        category TEXT NOT NULL,
        url TEXT NOT NULL,
        source_class TEXT NOT NULL,
        origin TEXT NOT NULL,
        provider TEXT,
        query TEXT,
        discovered_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS lead_discoveries_dedupe
        ON lead_discoveries(run_id, category, url);
    CREATE INDEX IF NOT EXISTS lead_discoveries_run
        ON lead_discoveries(run_id, discovered_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS message_offers (
        resource_id TEXT NOT NULL REFERENCES resources(id),
        offer_key TEXT NOT NULL,
        ended INTEGER NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY(resource_id, offer_key)
    );
    CREATE TABLE IF NOT EXISTS news_items (
        id TEXT PRIMARY KEY,
        resource_id TEXT NOT NULL REFERENCES resources(id),
        offer_key TEXT NOT NULL,
        task_id TEXT NOT NULL,
        category TEXT NOT NULL,
        discovered_at TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS news_items_resource ON news_items(resource_id, discovered_at);
    CREATE INDEX IF NOT EXISTS news_items_task ON news_items(task_id, discovered_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS source_definitions (
        id TEXT PRIMARY KEY,
        payload TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS source_states (
        source_id TEXT PRIMARY KEY,
        payload TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS source_entries (
        source_id TEXT NOT NULL,
        external_id TEXT NOT NULL,
        id TEXT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY(source_id, external_id)
    );
    CREATE INDEX IF NOT EXISTS source_entries_id ON source_entries(id);
    CREATE TABLE IF NOT EXISTS source_snapshots (
        id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS source_snapshots_source
        ON source_snapshots(source_id, fetched_at);
    """,
)

# Each action updates only what it names; state and favorites are independent.
REVIEW_STATES = {
    "confirm": ReviewState.CONFIRMED,
    "reject": ReviewState.REJECTED,
    "ignore": ReviewState.IGNORED,
    "reopen": ReviewState.OPEN,
}
REVIEW_FAVORITES = {"favorite": True, "unfavorite": False}


class UnknownResource(LookupError):
    """Raised when a review action names a resource that was never stored."""


class SettingsVersionConflict(Exception):
    """Raised when settings were written against a stale configuration version."""


def _review_from_row(row: sqlite3.Row) -> ResourceReview:
    return ResourceReview(
        resource_id=row["resource_id"],
        state=row["state"],
        favorite=bool(row["favorite"]),
        note=row["note"],
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _migrate(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    for step, script in enumerate(MIGRATIONS, start=1):
        if version >= step:
            continue
        connection.executescript(script)
    if version < len(MIGRATIONS):
        # PRAGMA statements cannot be parameterized; the value is a local constant.
        connection.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")


class Repository:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "radar.sqlite3"
        with self._connect() as connection:
            _migrate(connection)
            connection.execute("PRAGMA journal_mode=WAL")
        self._backfill_messages()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()


    @staticmethod
    def _message_reports(connection: sqlite3.Connection) -> dict[str, list[CollectedMessage]]:
        reports: dict[str, list[CollectedMessage]] = {}
        for row in connection.execute("SELECT resource_id, payload FROM message_offers ORDER BY rowid"):
            reports.setdefault(row["resource_id"], []).append(
                CollectedMessage.model_validate_json(row["payload"])
            )
        return reports

    @staticmethod
    def _with_messages(resource: Resource, reports: dict[str, list[CollectedMessage]]) -> Resource:
        resource.messages = reports.get(resource.id, resource.messages)
        return resource

    @staticmethod
    def _save_offer(connection: sqlite3.Connection, resource_id: str, message: CollectedMessage) -> None:
        connection.execute(
            "INSERT INTO message_offers(resource_id, offer_key, ended, payload) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(resource_id, offer_key) DO UPDATE SET "
            "ended=excluded.ended, payload=excluded.payload",
            (resource_id, message.offer_key, int(message.ended), message.model_dump_json()),
        )

    @staticmethod
    def _save_news(connection: sqlite3.Connection, event: NewsItem) -> None:
        connection.execute(
            "INSERT INTO news_items(id, resource_id, offer_key, task_id, category, discovered_at, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event.id, event.resource_id, event.offer_key, event.task_id, event.policy.category,
             event.discovered_at.isoformat(), event.model_dump_json()),
        )

    def _backfill_messages(self) -> None:
        """Retry safe local recovery, including databases with the old v1 marker."""
        self.recover_legacy_messages()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO settings_meta(key, value) VALUES ('messages_backfilled_v2', '1') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )

    def recover_legacy_messages(self) -> int:
        """Restore missing reports from saved evidence/tool JSON; no network or model."""
        resources = self.list_resources()
        ignored = self.ignored_ids()
        missing = [item for item in resources if not item.messages and item.id not in ignored]
        if not missing:
            return 0
        cached = cached_sources(self.data_dir)
        messages: list[CollectedMessage] = []
        for resource in missing:
            sources: list[MessageSource] = []
            for evidence in resource.evidence:
                try:
                    source = MessageSource(
                        url=evidence.url,
                        excerpt=evidence.quote,
                        source_type=evidence.source_type,
                        access="snippet",
                    )
                except ValueError:
                    continue
                if safe_source(source):
                    sources.append(source)
            sources = _merge_sources(sources, matching_sources(resource, resources, cached))
            if not sources:
                continue
            policy = Policy.model_validate(resource.model_dump(include=set(Policy.model_fields)))
            policy.resource_id = resource.id
            messages.append(CollectedMessage(
                policy=policy,
                title=f"{resource.provider} / {resource.service}",
                summary=_legacy_summary(resource),
                sources=sources,
            ))
        return len(self.import_legacy_messages(messages, None))

    def import_legacy_messages(
        self, messages: list[CollectedMessage], run: Run | None
    ) -> list[NewsItem]:
        """Fill existing identities only, preserving policy facts and original dates.

        A transaction rechecks both review state and message presence so automatic
        local recovery and an explicit backfill remain idempotent across processes.
        """
        events: list[NewsItem] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for incoming in messages:
                resource_id = incoming.policy.resource_id
                if not resource_id:
                    continue
                row = connection.execute(
                    "SELECT payload FROM resources WHERE id = ?", (resource_id,)
                ).fetchone()
                if row is None:
                    continue
                resource = Resource.model_validate_json(row[0])
                if resource.messages or connection.execute(
                    "SELECT 1 FROM message_offers WHERE resource_id = ?", (resource_id,)
                ).fetchone():
                    continue
                if self._stored_review(
                    connection, resource.id, resource.first_seen_at
                ).state == ReviewState.IGNORED:
                    continue
                if (
                    incoming.policy.category != resource.category
                    or incoming.policy.provider_domain != resource.provider_domain
                    or not _same_service(resource, incoming.policy)
                    or (run is not None and not run.scope.includes(resource))
                ):
                    continue
                sources = [source for source in incoming.sources if safe_source(source)]
                if not sources:
                    continue
                report = incoming.model_copy(deep=True, update={"sources": sources})
                if message_problem(report):
                    continue
                expired = resource.status == ResourceStatus.EXPIRED
                if expired:
                    report.ended = True
                    report.end_reason = (
                        resource.expiry_notes if _known(resource.expiry_notes)
                        else "历史核验记录显示该免费权益已结束"
                    )
                else:
                    reason = " ".join(report.end_reason.split())
                    report.ended = bool(
                        report.ended and reason
                        and reason in " ".join(source.excerpt for source in sources)
                    )
                    report.end_reason = reason if report.ended else ""
                event = NewsItem(
                    **report.model_dump(),
                    resource_id=resource.id,
                    task_id=run.id if run is not None else resource.last_task_id,
                    kind="expired" if report.ended else "new",
                    discovered_at=resource.first_seen_at,
                    first_seen_at=resource.first_seen_at,
                )
                self._save_offer(connection, resource.id, report)
                self._save_news(connection, event)
                resource.messages = [report]
                self._save_resource(connection, resource)
                events.append(event)
        return events

    def list_messages(
        self,
        category: Category | str | None = None,
        include_ended: bool = False,
        resource_id: str | None = None,
        task_id: str | None = None,
    ) -> list[NewsItem]:
        conditions = ["COALESCE(r.state, '') != ?"]
        arguments: list[object] = [str(ReviewState.IGNORED)]
        if category is not None:
            conditions.append("n.category = ?")
            arguments.append(str(Category(str(category))))
        if resource_id is not None:
            conditions.append("n.resource_id = ?")
            arguments.append(resource_id)
        if task_id is not None:
            conditions.append("n.task_id = ?")
            arguments.append(task_id)
        if not include_ended:
            # Every event of an offer that is currently ended stays in history mode.
            conditions.append("o.ended = 0")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT n.payload FROM news_items n "
                "JOIN message_offers o ON o.resource_id=n.resource_id AND o.offer_key=n.offer_key "
                "LEFT JOIN resource_reviews r ON r.resource_id=n.resource_id WHERE "
                + " AND ".join(conditions)
                + " ORDER BY n.discovered_at DESC, n.rowid DESC",
                arguments,
            ).fetchall()
        return [NewsItem.model_validate_json(row[0]) for row in rows]

    def apply_messages(self, batch: ResearchBatch, run: Run, now: datetime) -> list[NewsItem]:
        """Persist collected reports as immutable news events.

        Collection never rewrites verified policy facts, and only the report
        channel of a resource. Explicit endings need a stated reason, and an
        expiry must be present in a source excerpt.
        """
        now = aware_utc(now)
        events: list[NewsItem] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            reports = self._message_reports(connection)
            resources = [
                self._with_messages(Resource.model_validate_json(row[0]), reports)
                for row in connection.execute("SELECT payload FROM resources ORDER BY rowid")
            ]
            for incoming in batch.messages:
                policy = incoming.policy
                if not run.scope.includes(policy):
                    batch.failures.append(f"{policy.service}：消息超出本次范围，未写入")
                    continue
                try:
                    # Category is part of collection identity: text and image
                    # offers from one provider never coalesce into one resource.
                    previous = self._match(
                        policy,
                        [item for item in resources if item.category == policy.category],
                    )
                except ValueError as error:
                    batch.failures.append(f"{policy.service}：{error}")
                    continue
                if previous is not None:
                    if not run.scope.includes(previous):
                        batch.failures.append(f"{policy.service}：消息匹配到范围外资源，未写入")
                        continue
                    if self._stored_review(
                        connection, previous.id, now
                    ).state == ReviewState.IGNORED:
                        continue
                report = incoming.model_copy(deep=True)
                old = (
                    next(
                        (
                            item
                            for item in previous.messages
                            if item.offer_key == report.offer_key
                        ),
                        None,
                    )
                    if previous is not None
                    else None
                )
                if old is not None:
                    report = _merge_report(old, report)
                problem = message_problem(report)
                if problem:
                    batch.notes.append(f"{policy.service}：{problem}，未收录")
                    continue
                # An ending needs a stated reason backed by a source excerpt;
                # expiry needs the date present in a source excerpt.
                reason = " ".join(report.end_reason.split())
                excerpt_text = " ".join(item.excerpt for item in report.sources)
                report.ended = bool(report.ended and reason and reason in excerpt_text)
                if report.ended:
                    report.end_reason = reason
                expires_at = report.policy.expires_at
                if (
                    expires_at is not None
                    and expires_at <= now
                    and _sourced_expiry(report)
                ):
                    report.ended = True
                    report.end_reason = report.end_reason or "来源明确截止日期已到期"
                if old is not None:
                    reopened = any(
                        _REOPENED.search(source.excerpt) for source in incoming.sources
                    )
                    renewed = bool(
                        incoming.policy.expires_at
                        and incoming.policy.expires_at > now
                        and _sourced_expiry(incoming)
                    )
                    if old.ended and not report.ended and not (reopened or renewed):
                        # A repost without a reopening statement cannot resurrect an
                        # explicitly ended campaign.
                        report = report.model_copy(
                            deep=True,
                            update={"ended": True, "end_reason": old.end_reason},
                        )
                if not report.ended:
                    # An open offer never carries a stale ending statement.
                    report.end_reason = ""
                report = report.model_copy(
                    deep=True,
                    update={
                        "sources": _merge_sources(
                            old.sources if old is not None else [], report.sources
                        )
                    },
                )
                current = previous or Resource(
                    provider=policy.provider,
                    service=policy.service,
                    category=policy.category,
                    provider_domain=policy.provider_domain,
                    service_key=policy.service_key or _token(policy.service),
                    access_mode=policy.access_mode,
                    aliases=policy.aliases,
                    first_seen_at=now,
                    last_checked_at=now,
                )
                if previous is not None and not current.evidence:
                    # This resource carries no verified policy evidence, so its
                    # entry mode is message-derived; keep it aligned with the offer.
                    current.access_mode = report.policy.access_mode
                if previous is None:
                    # News rows reference the resource; claims stay out of verified fields.
                    self._save_resource(connection, current)
                latest = (
                    connection.execute(
                        "SELECT id, payload FROM news_items WHERE resource_id=? AND offer_key=? "
                        "ORDER BY discovered_at DESC, rowid DESC LIMIT 1",
                        (current.id, report.offer_key),
                    ).fetchone()
                    if old is not None
                    else None
                )
                prior = (
                    NewsItem.model_validate_json(latest["payload"]) if latest else None
                )
                changed = old is None or _message_facts(old) != _message_facts(report)
                if changed:
                    if report.ended:
                        kind = "expired"
                    elif old is None:
                        kind = "new"
                    else:
                        kind = "restored" if old.ended else "changed"
                    event = NewsItem(
                        **report.model_dump(),
                        resource_id=current.id,
                        task_id=run.id,
                        kind=kind,
                        discovered_at=now,
                        first_seen_at=prior.first_seen_at if prior else now,
                    )
                    self._save_news(connection, event)
                    events.append(event)
                elif (
                    old is not None
                    and prior is not None
                    and old.sources != report.sources
                    and latest is not None
                ):
                    # Source-only enrichment keeps the historical snapshot's event time.
                    prior.sources = report.sources
                    connection.execute(
                        "UPDATE news_items SET payload=? WHERE id=?",
                        (prior.model_dump_json(), latest["id"]),
                    )
                else:
                    continue
                self._save_offer(connection, current.id, report)
                current.messages = [
                    report if item.offer_key == report.offer_key else item
                    for item in current.messages
                ]
                if not any(item.offer_key == report.offer_key for item in current.messages):
                    current.messages = [*current.messages, report]
                self._save_resource(connection, current)
                resources = [item for item in resources if item.id != current.id] + [current]
        return events

    def translation_records(self) -> tuple[list[Resource], list[NewsItem]]:
        """All stored resources with their offers, plus every news snapshot, for zh backfill."""
        with self._connect() as connection:
            reports = self._message_reports(connection)
            resources = [
                self._with_messages(Resource.model_validate_json(row[0]), reports)
                for row in connection.execute(
                    "SELECT r.payload FROM resources r "
                    "LEFT JOIN resource_reviews v ON v.resource_id = r.id "
                    "WHERE COALESCE(v.state, '') != ? ORDER BY r.rowid",
                    (str(ReviewState.IGNORED),),
                )
            ]
            rows = connection.execute(
                "SELECT n.payload FROM news_items n "
                "LEFT JOIN resource_reviews r ON r.resource_id = n.resource_id "
                "WHERE COALESCE(r.state, '') != ? ORDER BY n.discovered_at, n.rowid",
                (str(ReviewState.IGNORED),),
            ).fetchall()
        return resources, [NewsItem.model_validate_json(row[0]) for row in rows]

    @staticmethod
    def _merge_message_zh(
        stored: CollectedMessage, translated: CollectedMessage
    ) -> CollectedMessage:
        """Overlay only *_zh fields; every other stored value stays untouched."""
        policy = stored.policy.model_copy(
            update={name: getattr(translated.policy, name) for name in POLICY_ZH_FIELDS}
        )
        return stored.model_copy(
            update={
                **{name: getattr(translated, name) for name in MESSAGE_ZH_FIELDS},
                "policy": policy,
            }
        )

    def save_message_translations(
        self, resource_id: str, messages: list[CollectedMessage]
    ) -> None:
        """Persist zh-only updates into stored offers and the resource's embedded copies."""
        if not messages:
            return
        by_key = {message.offer_key: message for message in messages}
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT offer_key, payload FROM message_offers WHERE resource_id = ?",
                (resource_id,),
            ).fetchall()
            for row in rows:
                translated = by_key.get(row["offer_key"])
                if translated is None:
                    continue
                stored = CollectedMessage.model_validate_json(row["payload"])
                merged = self._merge_message_zh(stored, translated)
                if merged != stored:
                    connection.execute(
                        "UPDATE message_offers SET payload=? WHERE resource_id=? AND offer_key=?",
                        (merged.model_dump_json(), resource_id, row["offer_key"]),
                    )
            row = connection.execute(
                "SELECT payload FROM resources WHERE id = ?", (resource_id,)
            ).fetchone()
            if row is not None:
                resource = Resource.model_validate_json(row["payload"])
                embedded = [
                    self._merge_message_zh(item, by_key[item.offer_key])
                    if item.offer_key in by_key
                    else item
                    for item in resource.messages
                ]
                if embedded != resource.messages:
                    self._save_resource(
                        connection, resource.model_copy(update={"messages": embedded})
                    )

    def save_news_translations(self, events: list[NewsItem]) -> None:
        """Persist zh-only updates into news snapshots, keeping event facts intact."""
        if not events:
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for event in events:
                row = connection.execute(
                    "SELECT payload FROM news_items WHERE id = ?", (event.id,)
                ).fetchone()
                if row is None:
                    continue
                stored = NewsItem.model_validate_json(row["payload"])
                merged = self._merge_message_zh(stored, event)
                if merged != stored:
                    connection.execute(
                        "UPDATE news_items SET payload=? WHERE id=?",
                        (merged.model_dump_json(), event.id),
                    )

    def save_resource_translations(self, resources: list[Resource]) -> None:
        """Persist policy zh fields (failure_reason_zh) without touching other content."""
        if not resources:
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for resource in resources:
                row = connection.execute(
                    "SELECT payload FROM resources WHERE id = ?", (resource.id,)
                ).fetchone()
                if row is None:
                    continue
                stored = Resource.model_validate_json(row["payload"])
                updated = stored.model_copy(
                    update={name: getattr(resource, name) for name in POLICY_ZH_FIELDS}
                )
                if updated != stored:
                    self._save_resource(connection, updated)



    def settings_version(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings_meta WHERE key = 'config_version'"
            ).fetchone()
        return int(row[0]) if row else 0

    def settings_overrides(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def settings_secret_rows(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name, ciphertext FROM settings_secrets ORDER BY name"
            ).fetchall()
        return {row["name"]: row["ciphertext"] for row in rows}

    def save_settings(
        self,
        overrides: Mapping[str, str | None],
        secrets: Mapping[str, str | None],
        expected_version: int,
    ) -> int:
        now = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT value FROM settings_meta WHERE key = 'config_version'"
            ).fetchone()
            current = int(row[0]) if row else 0
            if current != expected_version:
                raise SettingsVersionConflict(
                    f"settings version {current} does not match {expected_version}"
                )
            for key, value in overrides.items():
                if value is None:
                    connection.execute("DELETE FROM settings WHERE key = ?", (key,))
                else:
                    connection.execute(
                        "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                        "updated_at = excluded.updated_at",
                        (key, value, now),
                    )
            for name, ciphertext in secrets.items():
                if ciphertext is None:
                    connection.execute("DELETE FROM settings_secrets WHERE name = ?", (name,))
                else:
                    connection.execute(
                        "INSERT INTO settings_secrets(name, ciphertext, updated_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(name) DO UPDATE SET ciphertext = excluded.ciphertext, "
                        "updated_at = excluded.updated_at",
                        (name, ciphertext, now),
                    )
            version = current + 1
            connection.execute(
                "UPDATE settings_meta SET value = ? WHERE key = 'config_version'",
                (str(version),),
            )
        return version

    def list_resources(self, category=None, china_policy=None, status=None) -> list[Resource]:
        conditions: list[str] = []
        arguments: list[str] = []
        for name, value in (
            ("category", category),
            ("china_policy", china_policy),
            ("status", status),
        ):
            if value is not None:
                conditions.append(f"{name} = ?")
                arguments.append(str(value))
        sql = "SELECT payload FROM resources"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY rowid"
        with self._connect() as connection:
            reports = self._message_reports(connection)
            return [
                self._with_messages(Resource.model_validate_json(row[0]), reports)
                for row in connection.execute(sql, arguments)
            ]

    def get_resource(self, id: str) -> Resource | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM resources WHERE id = ?", (id,)).fetchone()
            return (
                self._with_messages(Resource.model_validate_json(row[0]), self._message_reports(connection))
                if row else None
            )

    def history(self, resource_id: str) -> list[Change]:
        return self._changes("resource_id", resource_id)

    def get_changes(self, task_id: str) -> list[Change]:
        return self._changes("task_id", task_id)

    def _changes(self, field: str, value: str) -> list[Change]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload FROM changes WHERE {field} = ? ORDER BY discovered_at, rowid",
                (value,),
            )
            return [Change.model_validate_json(row[0]) for row in rows]

    def list_runs(self) -> list[Run]:
        with self._connect() as connection:
            return [
                Run.model_validate_json(row[0])
                for row in connection.execute(
                    "SELECT payload FROM runs ORDER BY started_at DESC, rowid DESC"
                )
            ]

    def get_run(self, id: str) -> Run | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM runs WHERE id = ?", (id,)).fetchone()
            return Run.model_validate_json(row[0]) if row else None

    def save_run(self, run: Run) -> None:
        with self._connect() as connection:
            self._save_run(connection, run)

    @staticmethod
    def _save_run(connection: sqlite3.Connection, run: Run) -> None:
        connection.execute(
            "INSERT INTO runs(id, started_at, payload) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET started_at=excluded.started_at, payload=excluded.payload",
            (run.id, run.started_at.isoformat(), run.model_dump_json()),
        )

    def record_discoveries(self, run_id: str, discoveries: Iterable[LeadDiscovery]) -> int:
        """Persist leads for a run, skipping any already stored for the same key."""

        inserted = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for lead in discoveries:
                cursor = connection.execute(
                    "INSERT INTO lead_discoveries("
                    "run_id, category, url, source_class, origin, provider, query, discovered_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(run_id, category, url) DO NOTHING",
                    (
                        run_id,
                        lead.category,
                        lead.url,
                        lead.source_class,
                        lead.origin,
                        lead.provider,
                        lead.query,
                        lead.discovered_at.isoformat(),
                    ),
                )
                count = cursor.rowcount
                if count == -1:
                    count = connection.execute("SELECT changes()").fetchone()[0]
                inserted += count
        return inserted

    def discoveries_for_run(self, run_id: str) -> list[LeadDiscovery]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT category, url, source_class, origin, provider, query, discovered_at "
                "FROM lead_discoveries WHERE run_id = ? "
                "ORDER BY discovered_at, rowid",
                (run_id,),
            ).fetchall()
        return [
            LeadDiscovery.model_validate(
                {
                    "category": Category(row["category"]),
                    "url": row["url"],
                    "source_class": row["source_class"],
                    "origin": row["origin"],
                    "provider": row["provider"],
                    "query": row["query"],
                    "discovered_at": row["discovered_at"],
                }
            )
            for row in rows
        ]

    @staticmethod
    def _save_resource(connection: sqlite3.Connection, resource: Resource) -> None:
        connection.execute(
            "INSERT INTO resources(id,provider_domain,service_key,category,status,china_policy,payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "provider_domain=excluded.provider_domain,service_key=excluded.service_key,"
            "category=excluded.category,status=excluded.status,china_policy=excluded.china_policy,"
            "payload=excluded.payload",
            (
                resource.id,
                resource.provider_domain,
                resource.service_key,
                resource.category,
                resource.status,
                resource.china_policy,
                resource.model_dump_json(),
            ),
        )

    @staticmethod
    def _match(policy: Policy, resources: list[Resource]) -> Resource | None:
        if policy.resource_id:
            found = next((item for item in resources if item.id == policy.resource_id), None)
            if found is None:
                raise ValueError("显式资源标识不存在")
            if not policy.provider_domain or found.provider_domain != policy.provider_domain:
                raise ValueError("显式资源标识与提供商不匹配")
            if not _same_service(found, policy):
                raise ValueError("显式资源标识与具体 API 服务不匹配")
            return found
        same_provider = [
            item
            for item in resources
            if policy.provider_domain and item.provider_domain == policy.provider_domain
        ]
        exact = [
            item
            for item in same_provider
            if policy.service_key and item.service_key == policy.service_key
        ]
        if len(exact) == 1:
            return exact[0]
        matches = [item for item in same_provider if _same_service(item, policy)]
        if len(matches) > 1 or len(exact) > 1:
            raise ValueError("服务别名对应多个资源，无法安全判定身份")
        if matches:
            return matches[0]
        # Domainless discovery leads may be deduplicated by exact names only. They
        # cannot acquire official status or match a verified provider's records.
        if not policy.provider_domain:
            leads = [
                item
                for item in resources
                if not item.provider_domain
                and item.provider.casefold() == policy.provider.casefold()
                and item.service.casefold() == policy.service.casefold()
            ]
            if len(leads) == 1:
                return leads[0]
        return None

    @staticmethod
    def _stored_review(
        connection: sqlite3.Connection, resource_id: str, default_time: datetime
    ) -> ResourceReview:
        row = connection.execute(
            "SELECT resource_id, state, favorite, note, updated_at "
            "FROM resource_reviews WHERE resource_id = ?",
            (resource_id,),
        ).fetchone()
        if row is None:
            return ResourceReview(resource_id=resource_id, updated_at=default_time)
        return _review_from_row(row)

    def review(self, resource_id: str) -> ResourceReview:
        with self._connect() as connection:
            return self._stored_review(connection, resource_id, utc_now())

    def reviews(self) -> dict[str, ResourceReview]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT resource_id, state, favorite, note, updated_at "
                "FROM resource_reviews ORDER BY rowid"
            ).fetchall()
        return {row["resource_id"]: _review_from_row(row) for row in rows}

    def ignored_ids(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT resource_id FROM resource_reviews WHERE state = ?",
                (ReviewState.IGNORED,),
            ).fetchall()
        return {row["resource_id"] for row in rows}

    def actions(self, resource_id: str) -> list[UserAction]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM user_actions WHERE resource_id = ? "
                "ORDER BY created_at, rowid",
                (resource_id,),
            ).fetchall()
        return [UserAction.model_validate_json(row[0]) for row in rows]

    def apply_review(
        self,
        resource_id: str,
        action: ReviewAction,
        note: str = "",
        now: datetime | None = None,
    ) -> tuple[ResourceReview, UserAction | None]:
        moment = aware_utc(now) if now is not None else utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                "SELECT 1 FROM resources WHERE id = ?", (resource_id,)
            ).fetchone()
            if exists is None:
                raise UnknownResource(resource_id)
            current = self._stored_review(connection, resource_id, moment)
            updated = current.model_copy(deep=True)
            if action in REVIEW_STATES:
                updated.state = REVIEW_STATES[action]
            elif action in REVIEW_FAVORITES:
                updated.favorite = REVIEW_FAVORITES[action]
            elif action == "note":
                updated.note = note
            else:
                raise ValueError(f"未知审核动作：{action}")
            if (updated.state, updated.favorite, updated.note) == (
                current.state,
                current.favorite,
                current.note,
            ):
                return current, None
            updated.updated_at = moment
            connection.execute(
                "INSERT INTO resource_reviews(resource_id,state,favorite,note,updated_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(resource_id) DO UPDATE SET "
                "state=excluded.state, favorite=excluded.favorite, note=excluded.note, "
                "updated_at=excluded.updated_at",
                (
                    resource_id,
                    str(updated.state),
                    int(updated.favorite),
                    updated.note,
                    moment.isoformat(),
                ),
            )
            record = UserAction(
                resource_id=resource_id,
                action=action,
                before=current.model_dump(mode="json"),
                after=updated.model_dump(mode="json"),
                created_at=moment,
            )
            connection.execute(
                "INSERT INTO user_actions(id,resource_id,action,payload,created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    record.id,
                    resource_id,
                    action,
                    record.model_dump_json(),
                    moment.isoformat(),
                ),
            )
            return updated, record

    def apply_batch(self, batch: ResearchBatch, run: Run, now: datetime) -> list[Change]:
        now = aware_utc(now)
        changes: list[Change] = []
        with self._connect() as connection:
            # Take the writer lock before reading identities; a second process
            # cannot make a stale identity decision in the middle of this batch.
            connection.execute("BEGIN IMMEDIATE")
            resources = [
                Resource.model_validate_json(row[0])
                for row in connection.execute("SELECT payload FROM resources ORDER BY rowid")
            ]
            for incoming in batch.resources:
                if not run.scope.includes(incoming):
                    batch.failures.append(f"{incoming.service}：结果超出本次类别范围，未写入")
                    continue
                try:
                    previous = self._match(incoming, resources)
                except ValueError as error:
                    batch.failures.append(f"{incoming.service}：{error}")
                    continue
                if previous is not None and not run.scope.includes(previous):
                    batch.failures.append(f"{incoming.service}：匹配到范围外资源，未写入")
                    continue
                if incoming.check_status != CheckStatus.SUCCESS:
                    reason = incoming.failure_reason or "本次核查未完成，结论未获本次更新"
                    if previous:
                        current = previous.model_copy(
                            deep=True,
                            update={
                                "check_status": incoming.check_status,
                                "failure_reason": reason,
                                "last_checked_at": now,
                                "last_task_id": run.id,
                            },
                        )
                    else:
                        current = Resource(
                            provider=incoming.provider,
                            service=incoming.service,
                            category=incoming.category,
                            provider_domain=incoming.provider_domain,
                            service_key=incoming.service_key or _token(incoming.service),
                            access_mode=incoming.access_mode,
                            aliases=incoming.aliases,
                            check_status=incoming.check_status,
                            failure_reason=reason,
                            first_seen_at=now,
                            last_checked_at=now,
                            last_task_id=run.id,
                        )
                    self._save_resource(connection, current)
                    resources = [item for item in resources if item.id != current.id] + [current]
                    continue

                checked = validate_policy(incoming, now)
                if previous:
                    # An optional fact absent from this check neither proves nor
                    # disproves the previous explicit evidence.
                    carried: dict[str, Any] = {}
                    if not checked.quota_facts:
                        carried["quota_facts"] = previous.quota_facts
                    if not checked.model_deployments:
                        carried["model_deployments"] = previous.model_deployments
                    if carried:
                        checked = checked.model_copy(deep=True, update=carried)
                policy_data = checked.model_dump()
                policy_data["resource_id"] = None
                policy_data["service_key"] = (
                    previous.service_key
                    if previous
                    else checked.service_key or _token(checked.service)
                )
                if previous:
                    policy_data["aliases"] = list(
                        dict.fromkeys(
                            [
                                *previous.aliases,
                                previous.service,
                                previous.service_key,
                                *checked.aliases,
                                checked.service_key,
                            ]
                        )
                    )
                    policy_data["aliases"] = [value for value in policy_data["aliases"] if value]
                current = Resource(
                    **policy_data,
                    id=previous.id if previous else uuid4().hex,
                    first_seen_at=previous.first_seen_at if previous else now,
                    last_checked_at=now,
                    last_success_at=now,
                    last_task_id=run.id,
                    recommended_at=previous.recommended_at if previous else None,
                )
                current.messages = previous.messages if previous else []
                kind = None
                if previous is None:
                    kind = "expired" if current.status == ResourceStatus.EXPIRED else "new"
                elif _facts(previous) != _facts(current):
                    if (
                        current.status == ResourceStatus.EXPIRED
                        and previous.status != ResourceStatus.EXPIRED
                    ):
                        kind = "expired"
                    elif (
                        previous.status == ResourceStatus.EXPIRED
                        and current.status == ResourceStatus.ACTIVE
                    ):
                        kind = "restored"
                    else:
                        kind = "changed"
                if kind and kind != "expired" and eligible_recommendation(current, run.scope):
                    current.recommended_at = now
                self._save_resource(connection, current)
                resources = [item for item in resources if item.id != current.id] + [current]
                if kind:
                    change = Change(
                        resource_id=current.id,
                        task_id=run.id,
                        kind=kind,
                        before=_snapshot(previous) if previous else {},
                        after=_snapshot(current),
                        evidence=current.evidence,
                        discovered_at=now,
                    )
                    connection.execute(
                        "INSERT INTO changes(id,resource_id,task_id,discovered_at,payload) VALUES (?,?,?,?,?)",
                        (
                            change.id,
                            change.resource_id,
                            change.task_id,
                            now.isoformat(),
                            change.model_dump_json(),
                        ),
                    )
                    changes.append(change)
        return changes


    # --- Managed discovery sources -----------------------------------------
    @staticmethod
    def _entry_content_hash(entry: SourceEntry) -> str:
        published = entry.published_at.isoformat() if entry.published_at else ""
        payload = "\x1f".join(  # noqa: FLY002 - an explicit separator is clearer than escapes
            [entry.url, entry.title, entry.content, entry.raw_content, published]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def list_source_definitions(
        self, configured: Sequence[SourceDefinition] = ()
    ) -> list[SourceDefinition]:
        """Merge configured sources with stored overrides, stored facts winning."""
        with self._connect() as connection:
            stored = {
                row["id"]: SourceDefinition.model_validate_json(row["payload"])
                for row in connection.execute(
                    "SELECT id, payload FROM source_definitions ORDER BY id"
                )
            }
        merged: dict[str, SourceDefinition] = {}
        order: list[str] = []
        for source in configured:
            if source.id not in merged:
                order.append(source.id)
            merged[source.id] = source
        for source_id, source in stored.items():
            if source_id not in merged:
                order.append(source_id)
            # Local enable/review state is authoritative over config defaults.
            merged[source_id] = source
        return [merged[source_id] for source_id in order]

    def save_source_definition(self, source: SourceDefinition) -> SourceDefinition:
        source = SourceDefinition.model_validate(source)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO source_definitions(id, payload, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, "
                "updated_at=excluded.updated_at",
                (source.id, source.model_dump_json(), utc_now().isoformat()),
            )
        return source

    def get_source_state(self, source_id: str) -> SourceState | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM source_states WHERE source_id = ?", (source_id,)
            ).fetchone()
            return SourceState.model_validate_json(row[0]) if row else None

    def list_source_states(self) -> list[SourceState]:
        with self._connect() as connection:
            return [
                SourceState.model_validate_json(row[0])
                for row in connection.execute(
                    "SELECT payload FROM source_states ORDER BY source_id"
                )
            ]

    def get_source_entry(self, source_id: str, external_id: str) -> SourceEntry | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM source_entries WHERE source_id = ? AND external_id = ?",
                (source_id, external_id),
            ).fetchone()
            return SourceEntry.model_validate_json(row[0]) if row else None

    def list_source_entries(
        self, source_id: str | None = None, *, limit: int = 100, offset: int = 0
    ) -> list[SourceEntry]:
        conditions, arguments = "", []
        if source_id is not None:
            conditions = " WHERE source_id = ?"
            arguments.append(source_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM source_entries"
                + conditions
                + " ORDER BY json_extract(payload, '$.last_seen_at') DESC, rowid DESC"
                " LIMIT ? OFFSET ?",
                (*arguments, max(1, limit), max(0, offset)),
            ).fetchall()
        return [SourceEntry.model_validate_json(row[0]) for row in rows]

    def commit_source_scan(
        self,
        state: SourceState,
        entries: Sequence[SourceEntry],
        snapshot: SourceSnapshot | None = None,
    ) -> list[SourceEntry]:
        """Persist one source scan atomically: entries and snapshot, then state."""
        state = SourceState.model_validate(state)
        supplied = [SourceEntry.model_validate(entry) for entry in entries]
        if not state.source_id:
            raise ValueError("来源状态缺少来源标识")
        for entry in supplied:
            if entry.source_id != state.source_id:
                raise ValueError("来源条目与来源状态的作用域不一致")
        if snapshot is not None:
            snapshot = SourceSnapshot.model_validate(snapshot)
            if snapshot.source_id != state.source_id:
                raise ValueError("来源快照与来源状态的作用域不一致")
        persisted: list[SourceEntry] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = {
                row["external_id"]: SourceEntry.model_validate_json(row["payload"])
                for row in connection.execute(
                    "SELECT external_id, payload FROM source_entries WHERE source_id = ?",
                    (state.source_id,),
                )
            }
            for entry in supplied:
                content_hash = entry.content_hash or self._entry_content_hash(entry)
                old = existing.get(entry.external_id)
                if old is None:
                    value = entry.model_copy(update={"content_hash": content_hash, "revision": 1})
                else:
                    revised = content_hash != old.content_hash
                    value = entry.model_copy(
                        update={
                            "id": old.id,
                            "first_seen_at": old.first_seen_at,
                            "content_hash": content_hash,
                            "revision": old.revision + (1 if revised else 0),
                        }
                    )
                connection.execute(
                    "INSERT INTO source_entries(source_id, external_id, id, payload) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(source_id, external_id) DO UPDATE SET "
                    "id=excluded.id, payload=excluded.payload",
                    (state.source_id, value.external_id, value.id, value.model_dump_json()),
                )
                existing[value.external_id] = value
                persisted.append(value)
            if snapshot is not None:
                connection.execute(
                    "INSERT INTO source_snapshots(id, source_id, fetched_at, payload) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        snapshot.id,
                        snapshot.source_id,
                        snapshot.fetched_at.isoformat(),
                        snapshot.model_dump_json(),
                    ),
                )
            connection.execute(
                "INSERT INTO source_states(source_id, payload, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(source_id) DO UPDATE SET payload=excluded.payload, "
                "updated_at=excluded.updated_at",
                (state.source_id, state.model_dump_json(), utc_now().isoformat()),
            )
        return persisted

    def get_source_snapshot(self, snapshot_id: str) -> SourceSnapshot | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM source_snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
            return SourceSnapshot.model_validate_json(row[0]) if row else None

    def list_source_snapshots(self, source_id: str, *, limit: int = 20) -> list[SourceSnapshot]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM source_snapshots WHERE source_id = ? "
                "ORDER BY fetched_at DESC, rowid DESC LIMIT ?",
                (source_id, max(1, limit)),
            ).fetchall()
        return [SourceSnapshot.model_validate_json(row[0]) for row in rows]

    def mark_interrupted(self) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT payload FROM runs").fetchall()
            for row in rows:
                run = Run.model_validate_json(row[0])
                if run.status == "running":
                    run.status = "failed"
                    run.finished_at = now
                    run.error = "上次进程退出时任务尚未完成；结论未自动更新"
                    self._save_run(connection, run)

    def schedule_completed(self, day: str) -> bool:
        return any(
            run.schedule_day == day
            and run.trigger in {"scheduled", "catchup"}
            and run.finished_at is not None
            and run.status != "running"
            for run in self.list_runs()
        )

    def latest_schedule_day(self) -> str | None:
        days = [
            run.schedule_day
            for run in self.list_runs()
            if run.schedule_day
            and run.trigger in {"scheduled", "catchup"}
            and run.finished_at is not None
            and run.status != "running"
        ]
        return max(days) if days else None
