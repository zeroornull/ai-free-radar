"""Deterministic, one-layer queries derived only from observed discovery rows."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from .models import Category, ResearchGap


def _key(query: str) -> str:
    return " ".join(query.casefold().split())


def plan_gap_queries(
    category: Category,
    observations: Sequence[dict[str, str]],
    seen_queries: Iterable[str] = (),
    limit: int = 3,
) -> list[ResearchGap]:
    """Plan bounded followups; discovery of a URL never establishes a policy fact.

    A domain is the stable entity when a title supplies no explicit alias. Queries
    retain observed credit/trial vocabulary instead of assuming every offer says
    'free tier'. The input is the frozen first pass, never followup results.
    """
    seen = {_key(query) for query in seen_queries}
    entities: set[tuple[str, str]] = set()
    seen_urls: set[str] = set()
    planned: list[ResearchGap] = []
    for row in observations:
        if len(planned) >= max(0, limit):
            break
        url = row.get("url", "")
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower().removeprefix("www.")
            if parsed.scheme not in {"http", "https"} or not host or "." not in host:
                continue
        except ValueError:
            continue
        url_key = _url_key(url)
        if url_key in seen_urls:
            continue
        seen_urls.add(url_key)
        title = " ".join(row.get("title", "").split())[:160]
        text = title + " " + row.get("snippet", "")
        aliases = re.findall(
            r"(?:formerly|also known as|renamed (?:from|to)|aka|原名|更名为|又称)\s*[:：]?\s*[\"“]?([\w][\w .-]{1,48})",
            text,
            flags=re.IGNORECASE,
        )
        vocabulary = re.search(
            r"\b(?:free credits?|trial credits?|credits?|trial|free tier|free plan|free)\b|免费|赠额|试用",
            text,
            flags=re.IGNORECASE,
        )
        if not vocabulary and not aliases:
            continue
        term = vocabulary.group(0).casefold() if vocabulary else "API"
        entity = host
        alias = re.split(r"[,;。|]|\s+(?:with|and|offers?|provides?)\b", aliases[0], maxsplit=1, flags=re.IGNORECASE)[0].strip() if aliases else ""
        identity = (entity, alias.casefold())
        if identity in entities:
            continue
        entities.add(identity)
        if alias:
            query = f'"{alias}" "{host}" {term} API pricing documentation'
            goal = f"查找已观察别名 {alias} 与 {host} 的官方 API 额度及适用条件证据"
        else:
            query = f'"{host}" {term} API quota eligibility expiry documentation'
            goal = f"补充 {host} 已提及的 {term} 的 API 额度、资格与有效期原文"
        normalized = _key(query)
        if normalized in seen:
            continue
        seen.add(normalized)
        source_id = row.get("source_id", "")
        planned.append(ResearchGap(
            id=hashlib.sha256(f"{category.value}\n{normalized}".encode()).hexdigest()[:24],
            category=category,
            query=query,
            goal=goal,
            trigger_url=url,
            source_ids=[source_id] if source_id else [],
        ))
    return planned




GapStopReason = Literal[
    "gap_resolved", "no_new_evidence", "budget_exhausted",
    "provider_failed", "duplicate_query", "pending",
]


def _url_key(url: str) -> str:
    parsed = urlsplit(url.strip())
    return urlunsplit((
        parsed.scheme.lower(),
        (parsed.hostname or "").lower() + (f":{parsed.port}" if parsed.port else ""),
        parsed.path or "/",
        parsed.query,
        "",
    ))


_FREE_TERMS = re.compile(
    r"free|trial|credits?|quota|免费|赠额|试用|额度|免费额度", re.IGNORECASE
)
_QUANTIFIED = re.compile(
    r"\b\d[\d,.]*\s*(?:%|credits?|tokens?|requests?|calls?|rpm|rpd|usd|\$|万|次)"
    r"|per\s+(?:day|month|week)|\b(?:daily|monthly)\b|\bfree (?:tier|plan)\b|免费额度|每[天月周]",
    re.IGNORECASE,
)


def has_quota_statement(text: str) -> bool:
    """Whether observed text states a quantified free/quota offer, not merely a price."""
    normalized = " ".join(text.split())
    return bool(_FREE_TERMS.search(normalized) and _QUANTIFIED.search(normalized))


def new_result_urls(
    result_rows: Sequence[dict[str, str]], known_urls: Iterable[str]
) -> list[str]:
    """Return result URLs not yet read or observed, deduplicated within the layer."""
    known = {_url_key(url) for url in known_urls if url}
    fresh: list[str] = []
    for row in result_rows:
        url = row.get("url", "")
        if not url:
            continue
        key = _url_key(url)
        if key in known:
            continue
        known.add(key)
        fresh.append(url)
    return fresh


@dataclass(frozen=True)
class GapOutcome:
    """Network-free outcome of one gap attempt, shared by runtime and replay."""

    stop_reason: GapStopReason
    new_result_urls: list[str]
    new_evidence_urls: list[str]


def evaluate_gap_outcome(
    *,
    result_rows: Sequence[dict[str, str]] = (),
    known_urls: Iterable[str] = (),
    read_pages: Sequence[tuple[str, str]] = (),
    duplicate_query: bool = False,
    search_failed: bool = False,
    search_budget_exhausted: bool = False,
    fetch_budget_exhausted: bool = False,
) -> GapOutcome:
    """Classify a single gap layer without network or model access.

    A newly returned search URL is never evidence by itself: only text actually
    fetched this layer that states a quantified quota/free term resolves the gap.
    """
    if duplicate_query:
        return GapOutcome("duplicate_query", [], [])
    if search_budget_exhausted:
        return GapOutcome("budget_exhausted", [], [])
    if search_failed:
        return GapOutcome("provider_failed", [], [])
    fresh = new_result_urls(result_rows, known_urls)
    if not fresh:
        return GapOutcome("no_new_evidence", [], [])
    evidence: list[str] = []
    seen_pages: set[str] = set()
    for url, text in read_pages:
        key = _url_key(url)
        if key in seen_pages:
            continue
        seen_pages.add(key)
        if has_quota_statement(text):
            evidence.append(url)
    if evidence:
        return GapOutcome("gap_resolved", fresh, evidence)
    if fetch_budget_exhausted:
        return GapOutcome("budget_exhausted", fresh, [])
    return GapOutcome("no_new_evidence", fresh, [])


@dataclass(frozen=True)
class ObservedText:
    """One actually observed source excerpt and how the reader accessed it."""

    url: str
    text: str
    access: Literal["page", "snippet", "feed", "catalog"] = "page"


@dataclass(frozen=True)
class QuotaCandidate:
    source_url: str
    quote: str
    amount: float | None = None
    unit: str = ""
    condition: str = ""
    value_phrase: str = ""


@dataclass(frozen=True)
class DeploymentCandidate:
    source_url: str
    quote: str
    provider: str
    model_id: str
    base_model: str = ""


@dataclass(frozen=True)
class FactVerdict:
    accepted: bool
    warning: str = ""


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _numeric_values(text: str) -> list[float]:
    values: list[float] = []
    for token in re.findall(r"\d[\d,]*(?:\.\d+)?\s*(?:k|m|million|thousand)?", text.casefold()):
        number = re.match(r"[\d,.]+", token)
        if number is None:
            continue
        raw = number.group(0).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        suffix = token[len(number.group(0)):].strip()
        if suffix in {"k", "thousand"}:
            value *= 1_000
        elif suffix in {"m", "million"}:
            value *= 1_000_000
        values.append(value)
    return values


def _quote_observed(quote: str, text: str) -> bool:
    normalized = _normalized(quote)
    return len(normalized) >= 8 and normalized in _normalized(text)


def evaluate_quota_fact(
    fact: QuotaCandidate, observations: Sequence[ObservedText]
) -> FactVerdict:
    """Accept a quota only when its quote and numbers come from an observed excerpt.

    Catalog metadata can never establish a free/quota policy, and an amount without
    a unit or condition in the same quote is not evidence-supported.
    """
    key = _url_key(fact.source_url)
    for observed in observations:
        if observed.access == "catalog" or _url_key(observed.url) != key:
            continue
        if not _quote_observed(fact.quote, observed.text):
            break
        if not fact.unit.strip() or _normalized(fact.unit) in {"", "未说明", "unknown"}:
            return FactVerdict(False, "额度字段缺少原文可证明的计量单位")
        if _normalized(fact.unit) not in _normalized(fact.quote):
            return FactVerdict(False, "额度单位不在来源引文中")
        if fact.amount is not None and fact.amount not in _numeric_values(fact.quote):
            return FactVerdict(False, "额度数值不在来源引文中")
        if fact.condition.strip() and _normalized(fact.condition) not in _normalized(
            fact.quote
        ):
            return FactVerdict(False, "额度适用条件不在来源引文中")
        if fact.value_phrase.strip() and _normalized(fact.value_phrase) not in _normalized(
            fact.quote
        ):
            return FactVerdict(False, "额度措辞不在来源引文中")
        return FactVerdict(True)
    return FactVerdict(False, "额度字段缺少实际观察来源原文支撑")


def evaluate_model_deployment(
    deployment: DeploymentCandidate, observations: Sequence[ObservedText]
) -> FactVerdict:
    """Accept only an explicit provider/model mapping present in observed text."""
    key = _url_key(deployment.source_url)
    for observed in observations:
        if _url_key(observed.url) != key:
            continue
        if not _quote_observed(deployment.quote, observed.text):
            break
        quote = _normalized(deployment.quote)
        if not deployment.provider.strip() or _normalized(deployment.provider) not in quote:
            return FactVerdict(False, "部署映射缺少引文中的提供方")
        if not deployment.model_id.strip() or _normalized(deployment.model_id) not in quote:
            return FactVerdict(False, "部署映射缺少引文中的模型 ID")
        if deployment.base_model.strip() and _normalized(
            deployment.base_model
        ) not in quote:
            return FactVerdict(False, "部署映射缺少引文中的基础模型")
        return FactVerdict(True)
    return FactVerdict(False, "部署映射缺少实际观察来源原文支撑")
