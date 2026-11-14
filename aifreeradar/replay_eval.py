"""Deterministic frozen evidence replay; never constructs research or network clients."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .models import UNKNOWN, Category, ModelDeployment, QuotaFact
from .research_planning import (
    DeploymentCandidate,
    ObservedText,
    QuotaCandidate,
    evaluate_gap_outcome,
    evaluate_model_deployment,
    evaluate_quota_fact,
    new_result_urls,
    plan_gap_queries,
)

DEFAULT_CASES = Path(__file__).resolve().parent.parent / "benchmark" / "replay_cases.json"
_FACT_MODELS = {"quota_fact": QuotaFact, "model_deployment": ModelDeployment}
_UNKNOWN_FACT_FIELDS = {"amount", "unit", "period", "scope", "condition", "model_ids"}


def _text(value: str) -> str:
    return " ".join(value.casefold().split())


def _url(value: str) -> str:
    return value.rstrip("/")


def _has_phrase(needle: str, haystack: str) -> bool:
    """Whitespace tolerant match; a short phrase never matches inside a longer token."""
    needle, haystack = _text(needle), _text(haystack)
    if not needle:
        return False
    return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack) is not None


class ReplayRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Observation(ReplayRecord):
    url: str = Field(min_length=1)
    title: str = ""
    snippet: str = ""
    text: str = ""
    source_id: str = ""
    external_id: str = ""
    revision: int = Field(default=1, ge=1)
    access: Literal["snippet", "page", "feed", "catalog"] = "snippet"

    def evidence(self) -> str:
        return self.text or self.snippet

    def planner_row(self) -> dict[str, str]:
        return {
            "url": self.url, "title": self.title,
            "snippet": self.snippet or self.text, "source_id": self.source_id,
        }


class ExpectedTarget(ReplayRecord):
    id: str = Field(min_length=1)
    urls: list[str] = Field(min_length=1)
    evidence_phrases: list[str] = Field(min_length=1)
    # Curated free-API announcement identity: provider/service URL plus real wording.
    # Catalog rows never prove an announcement; strict fact evidence still needs a page.


class ProviderOutcome(ReplayRecord):
    trigger_url: str
    source_id: str = ""
    status: Literal["ok", "failed"] = "ok"
    results: list[Observation] = Field(default_factory=list)
    pages: list[Observation] = Field(default_factory=list)
    error: str = ""

    @model_validator(mode="after")
    def page_access(self) -> ProviderOutcome:
        if any(page.access != "page" for page in self.pages):
            raise ValueError("provider_outcomes.pages must contain fetched page excerpts")
        if any(row.access == "page" for row in self.results):
            raise ValueError("fetched pages belong in pages, not search results")
        if self.status == "failed" and (self.results or self.pages):
            raise ValueError("a failed provider cannot supply successful observations")
        return self


class Budgets(ReplayRecord):
    search_limit: int = Field(default=16, ge=0)
    fetch_limit: int = Field(default=32, ge=0)
    baseline_search_calls: int = Field(default=6, ge=0)
    baseline_fetch_calls: int = Field(default=0, ge=0)
    gap_limit: int = Field(default=3, ge=0, le=4)


class FieldClaim(ReplayRecord):
    """Candidate optional fact validated by the exact Policy fact models."""

    kind: Literal["quota_fact", "model_deployment"]
    payload: dict[str, Any]
    expect: Literal["accepted", "rejected"] = "accepted"


class ExpectedGap(ReplayRecord):
    trigger_url: str
    target_ids: list[str] = Field(min_length=1)


class ReplayCase(ReplayRecord):
    id: str = Field(min_length=1)
    description: str = ""
    category: Category
    observations: list[Observation]
    known_queries: list[str] = Field(default_factory=list)
    budgets: Budgets = Field(default_factory=Budgets)
    provider_outcomes: list[ProviderOutcome] = Field(default_factory=list)
    expected_targets: list[ExpectedTarget] = Field(default_factory=list)
    expected_gaps: list[ExpectedGap] = Field(default_factory=list)
    field_claims: list[FieldClaim] = Field(default_factory=list)
    required_unknowns: list[str] = Field(default_factory=list)
    captured_traces: list[dict[str, Any]] | None = None
    # A copied GET /api/tasks/{id} response may be supplied; no API request occurs.
    captured_run: dict[str, Any] | None = None
    expectations: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unambiguous_truth(self) -> ReplayCase:
        ids = [target.id for target in self.expected_targets]
        if len(ids) != len(set(ids)):
            raise ValueError("expected target IDs must be distinct")
        keys = [(outcome.trigger_url, outcome.source_id) for outcome in self.provider_outcomes]
        if len(keys) != len(set(keys)):
            raise ValueError("provider outcomes must have distinct trigger/source keys")
        if any(set(gap.target_ids) - set(ids) for gap in self.expected_gaps):
            raise ValueError("expected gap refers to an unknown target ID")
        if set(self.required_unknowns) - _UNKNOWN_FACT_FIELDS:
            raise ValueError("required_unknowns must name optional factual fields")
        if self.captured_traces is not None and self.captured_run is not None:
            raise ValueError("supply captured_traces or captured_run, not both")
        if self.captured_run is not None and not isinstance(
            self.captured_run.get("research_traces"), list
        ):
            raise ValueError("captured_run must contain research_traces")
        return self


def load_replay_cases(path: Path | str) -> list[ReplayCase]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        return _cases(document)
    except (OSError, ValueError, TypeError) as error:
        raise ValueError(f"cannot load replay cases: {error}") from error


def _cases(document: Any) -> list[ReplayCase]:
    if isinstance(document, dict) and "cases" in document:
        if document.get("schema_version", 1) != 1:
            raise ValueError("unsupported replay schema_version")
        rows = document["cases"]
    elif isinstance(document, dict):
        rows = [document]
    else:
        rows = document
    if not isinstance(rows, list) or not rows:
        raise ValueError("replay input must contain a nonempty cases list")
    cases = [row if isinstance(row, ReplayCase) else ReplayCase.model_validate(row) for row in rows]
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("replay case IDs must be distinct")
    return cases


def _matched(targets: Sequence[ExpectedTarget], rows: Sequence[Observation]) -> set[str]:
    return {
        target.id for target in targets
        if any(
            row.access != "catalog"
            and _url(row.url) in {_url(url) for url in target.urls}
            and any(_has_phrase(phrase, row.evidence()) for phrase in target.evidence_phrases)
            for row in rows
        )
    }


def _observed(rows: Sequence[Observation]) -> list[ObservedText]:
    return [
        ObservedText(url=row.url, text=row.evidence(), access=row.access)
        for row in rows
    ]


def _evaluate_claim(claim: FieldClaim, rows: Sequence[Observation]) -> dict[str, Any]:
    """Validate through Policy's real fact model, then shared evidence predicates."""
    model = _FACT_MODELS[claim.kind]
    try:
        fact = model.model_validate(claim.payload)
    except ValidationError as error:
        return {"kind": claim.kind, "accepted": False,
                "reason": str(error).splitlines()[0]}
    observations = _observed([row for row in rows if row.access != "snippet"])
    observations.sort(key=lambda item: item.access != "page")
    if claim.kind == "quota_fact":
        assert isinstance(fact, QuotaFact)
        verdict = evaluate_quota_fact(
            QuotaCandidate(
                source_url=fact.source_url, quote=fact.quote, amount=fact.amount,
                unit=fact.unit, condition=fact.condition, value_phrase=fact.value_phrase,
            ),
            observations,
        )
    else:
        assert isinstance(fact, ModelDeployment)
        verdict = evaluate_model_deployment(
            DeploymentCandidate(
                source_url=fact.source_url, quote=fact.quote, provider=fact.provider,
                model_id=fact.model_id, base_model=fact.base_model,
            ),
            observations,
        )
    if not verdict.accepted:
        return {"kind": claim.kind, "accepted": False, "reason": verdict.warning}
    return {"kind": claim.kind, "accepted": True, "fact": fact.model_dump(mode="json")}


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _simulate(case: ReplayCase) -> tuple[list[dict[str, Any]], list[Observation], int, int]:
    gaps = plan_gap_queries(
        case.category, [row.planner_row() for row in case.observations],
        case.known_queries, case.budgets.gap_limit,
    )
    rows = list(case.observations)
    search_calls = case.budgets.baseline_search_calls
    fetch_calls = case.budgets.baseline_fetch_calls
    traces: list[dict[str, Any]] = []
    fetched = {_url(row.url) for row in rows if row.access == "page"}
    for gap in gaps:
        trace = gap.model_dump(mode="json")
        trace.update(result_urls=[], new_evidence_urls=[], search_calls=0, fetch_calls=0)
        if search_calls >= case.budgets.search_limit:
            verdict = evaluate_gap_outcome(search_budget_exhausted=True)
            trace["stop_reason"] = verdict.stop_reason
            traces.append(trace)
            continue
        search_calls += 1
        trace["search_calls"] = 1
        candidates = [
            frozen for frozen in case.provider_outcomes
            if frozen.trigger_url == gap.trigger_url
            and (not frozen.source_id or frozen.source_id in gap.source_ids)
        ]
        if len(candidates) != 1:
            raise ValueError(
                f"{case.id}: each executed gap requires one frozen provider outcome: "
                f"{gap.trigger_url}"
            )
        frozen = candidates[0]
        known_urls = [row.url for row in rows]
        if frozen.status == "failed":
            verdict = evaluate_gap_outcome(search_failed=True)
            trace["error"] = frozen.error
        else:
            result_rows = [row.planner_row() for row in frozen.results]
            rows.extend(frozen.results)
            read_pages: list[tuple[str, str]] = []
            fetch_exhausted = False
            fresh = new_result_urls(result_rows, known_urls)
            if fresh:
                for page in frozen.pages:
                    if _url(page.url) in fetched:
                        continue
                    if fetch_calls >= case.budgets.fetch_limit:
                        fetch_exhausted = True
                        break
                    fetch_calls += 1
                    trace["fetch_calls"] += 1
                    fetched.add(_url(page.url))
                    rows.append(page)
                    read_pages.append((page.url, page.evidence()))
            verdict = evaluate_gap_outcome(
                result_rows=result_rows, known_urls=known_urls, read_pages=read_pages,
                fetch_budget_exhausted=fetch_exhausted,
            )
        trace["stop_reason"] = verdict.stop_reason
        trace["result_urls"] = verdict.new_result_urls
        trace["new_evidence_urls"] = verdict.new_evidence_urls
        traces.append(trace)
    return traces, rows, search_calls, fetch_calls


def _trace_metrics(
    case: ReplayCase, traces: list[dict[str, Any]], rows: Sequence[Observation],
    search_calls: int, fetch_calls: int,
) -> dict[str, Any]:
    known = {_text(query) for query in case.known_queries}
    duplicates = 0
    false_resolved = 0
    for trace in traces:
        if not isinstance(trace, dict) or not isinstance(trace.get("query"), str):
            raise TypeError(f"{case.id}: captured trace must have a string query")
        query = _text(trace["query"])
        duplicates += int(query in known)
        known.add(query)
        if trace.get("stop_reason") != "gap_resolved":
            continue
        expected = next(
            (set(goal.target_ids) for goal in case.expected_gaps
             if goal.trigger_url == trace.get("trigger_url")),
            set(),
        )
        evidence_urls = {_url(url) for url in trace.get("new_evidence_urls", [])}
        evidence = [
            row for row in rows
            if row.access == "page" and _url(row.url) in evidence_urls
        ]
        # A trace cannot manufacture a fetched excerpt by merely claiming a URL.
        false_resolved += int(not (expected & _matched(case.expected_targets, evidence)))
    return {
        "duplicate_queries": duplicates,
        "duplicate_query_rate": _ratio(duplicates, len(traces)),
        "budget_violations": int(search_calls > case.budgets.search_limit)
        + int(fetch_calls > case.budgets.fetch_limit),
        "search_budget_excess": max(0, search_calls - case.budgets.search_limit),
        "fetch_budget_excess": max(0, fetch_calls - case.budgets.fetch_limit),
        "false_resolved_gaps": false_resolved,
    }


def _captured_counts(traces: list[dict[str, Any]], field: str) -> int:
    total = 0
    for trace in traces:
        value = trace.get(field, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"captured {field} must be a nonnegative integer")
        total += value
    return total


def evaluate_case(case: ReplayCase) -> dict[str, Any]:
    traces, rows, search_calls, fetch_calls = _simulate(case)
    baseline = _matched(case.expected_targets, case.observations)
    final = _matched(case.expected_targets, rows)
    added = final - baseline
    claim_results = [_evaluate_claim(claim, rows) for claim in case.field_claims]
    accepted = [result for result in claim_results if result["accepted"]]
    supported = sum(
        result["accepted"] and claim.expect == "accepted"
        for claim, result in zip(case.field_claims, claim_results, strict=True)
    )
    fact_mismatches = [
        {"kind": claim.kind, "expected": claim.expect, "observed": result["accepted"],
         "reason": result.get("reason", "")}
        for claim, result in zip(case.field_claims, claim_results, strict=True)
        if claim.expect == "accepted" and not result["accepted"]
    ]
    accepted_facts = [result["fact"] for result in accepted]
    unknown_violations: list[str] = []
    for fact in accepted_facts:
        for field in case.required_unknowns:
            value = fact.get(field)
            if field == "model_ids":
                if value:
                    unknown_violations.append(field)
            elif value not in (None, "", UNKNOWN, "unspecified"):
                unknown_violations.append(field)
    requests = (search_calls - case.budgets.baseline_search_calls
                + fetch_calls - case.budgets.baseline_fetch_calls)
    metrics = _trace_metrics(case, traces, rows, search_calls, fetch_calls)
    metrics.update(
        expected_targets=len(case.expected_targets), baseline_targets=len(baseline),
        final_targets=len(final), added_targets=len(added),
        baseline_recall=_ratio(len(baseline), len(case.expected_targets)),
        final_recall=_ratio(len(final), len(case.expected_targets)),
        added_target_recall=_ratio(len(added), len(case.expected_targets)),
        additional_requests=requests, requests_per_added_target=_ratio(requests, len(added)),
        search_calls=search_calls, fetch_calls=fetch_calls,
        field_claims=len(case.field_claims), supported_field_claims=supported,
        field_evidence_support=_ratio(supported, len(case.field_claims)),
        false_fact_acceptance=sum(
            result["accepted"] and claim.expect == "rejected"
            for claim, result in zip(case.field_claims, claim_results, strict=True)
        ),
        unknown_preservation_violations=len(set(unknown_violations)),
    )
    result: dict[str, Any] = {
        "id": case.id, "description": case.description, "metrics": metrics,
        "baseline_target_ids": sorted(baseline), "added_target_ids": sorted(added),
        "missing_target_ids": sorted({target.id for target in case.expected_targets} - final),
        "planned_gap_count": len(traces), "stop_reasons": [t["stop_reason"] for t in traces],
        "unknown_violations": sorted(set(unknown_violations)),
        "field_claim_results": claim_results, "fact_mismatches": fact_mismatches,
        "traces": traces,
    }
    captured = case.captured_traces
    if case.captured_run is not None:
        captured = case.captured_run["research_traces"]
    if captured is not None:
        captured_search = case.budgets.baseline_search_calls + _captured_counts(
            captured, "search_calls"
        )
        # Runtime ResearchTrace currently omits fetch_calls; report that gap honestly.
        fetch_known = all("fetch_calls" in trace for trace in captured)
        captured_fetch = case.budgets.baseline_fetch_calls + _captured_counts(
            captured, "fetch_calls"
        )
        result["captured_metrics"] = _trace_metrics(
            case, captured, rows, captured_search, captured_fetch
        )
        result["captured_metrics"].update(
            search_calls=captured_search,
            fetch_calls=captured_fetch if fetch_known else None,
            fetch_budget_observable=fetch_known,
        )
    failures: list[str] = []
    for key, expected in case.expectations.items():
        actual = result.get(key, metrics.get(key))
        if key.startswith("captured."):
            actual = result.get("captured_metrics", {}).get(key.removeprefix("captured."))
        if actual != expected:
            failures.append(f"{key}: expected {expected!r}, observed {actual!r}")
    result["expectation_failures"] = failures
    return result


def evaluate_replay(document: Any) -> dict[str, Any]:
    """Evaluate a case, cases list or versioned envelope without I/O or mutable state.

    Recall uses curated target identities, URLs AND announcement evidence phrases.
    It measures this finite frozen sample only, never the universe of free APIs.
    """
    cases = _cases(document)
    results = [evaluate_case(case) for case in cases]
    additive = (
        "expected_targets", "baseline_targets", "final_targets", "added_targets",
        "additional_requests", "duplicate_queries", "budget_violations", "false_resolved_gaps",
        "field_claims", "supported_field_claims", "false_fact_acceptance",
        "unknown_preservation_violations",
    )
    totals: dict[str, Any] = {
        key: sum(result["metrics"][key] for result in results) for key in additive
    }
    totals.update(
        baseline_recall=_ratio(totals["baseline_targets"], totals["expected_targets"]),
        final_recall=_ratio(totals["final_targets"], totals["expected_targets"]),
        requests_per_added_target=_ratio(totals["additional_requests"], totals["added_targets"]),
        duplicate_query_rate=_ratio(
            totals["duplicate_queries"], sum(result["planned_gap_count"] for result in results)
        ),
        field_evidence_support=_ratio(
            totals["supported_field_claims"], totals["field_claims"]
        ),
        expectation_failures=sum(len(result["expectation_failures"]) for result in results),
    )
    return {
        "schema_version": 1,
        "scope": "finite frozen sample; not universe coverage or a live availability check",
        "network_used": False, "summary": totals, "cases": results,
    }


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    totals = report["summary"]
    lines = [
        "# 冻结证据回放评测", "",
        "仅度量有限冻结样本，不代表全部免费 API 的覆盖率、实时性或可用性。无网络、无模型调用。", "",
        (
            f"基线召回：{totals['baseline_targets']}/{totals['expected_targets']}；"
            f"补搜后：{totals['final_targets']}/{totals['expected_targets']}；"
            f"新增目标：{totals['added_targets']}。"
        ), "",
        "目标按人工标注身份、来源 URL 及免费 API 公告原文匹配；返回列表长度不计作召回。", "",
        "| 样本 | 基线/目标 | 补搜后/目标 | 新增请求 | 每新增目标请求 | 重复查询 | 预算越界 | 错误关闭缺口 | 字段证据 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case in report["cases"]:
        m = case["metrics"]
        cost = m["requests_per_added_target"]
        cost_text = f"{cost:.2f}" if cost is not None else "未定义"
        evidence = f"{m['supported_field_claims']}/{m['field_claims']}"
        lines.append(
            f"| {_cell(case['id'])} | {m['baseline_targets']}/{m['expected_targets']} | "
            f"{m['final_targets']}/{m['expected_targets']} | {m['additional_requests']} | "
            f"{cost_text} | {m['duplicate_queries']} | {m['budget_violations']} | "
            f"{m['false_resolved_gaps']} | {evidence} |"
        )
    lines.extend(["", "无新增目标时每新增目标请求成本为未定义（JSON 为 null），不写成零。", ""])
    for case in report["cases"]:
        lines.extend([
            f"## {_cell(case['id'])}", "", case["description"], "",
            (
                f"新增目标：{', '.join(case['added_target_ids']) or '无'}；"
                f"未召回：{', '.join(case['missing_target_ids']) or '无'}。"
            ), "",
            "停止原因：" + (", ".join(case["stop_reasons"]) or "未计划补搜") + "。", "",
        ])
        if case["fact_mismatches"] or case["unknown_violations"]:
            reasons = "; ".join(
                f"{item['kind']}: {item['reason']}" for item in case["fact_mismatches"]
            )
            lines.extend([
                "字段期望不符：" + (reasons or "无") + "；"
                "未知项被填实：" + (", ".join(case["unknown_violations"]) or "无") + "。", "",
            ])
        if "captured_metrics" in case:
            lines.extend([
                "捕获轨迹比较："
                + "`" + json.dumps(case["captured_metrics"], ensure_ascii=False) + "`", "",
            ])
        for failure in case["expectation_failures"]:
            lines.extend([f"- 期望不符：{failure}", ""])
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="无网络冻结回放：调用运行时同一缺口 planner。")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument("--output", type=Path, help="显式报告路径；省略则写 stdout")
    args = parser.parse_args(argv)
    try:
        report = evaluate_replay(load_replay_cases(args.cases))
        body = (
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            if args.format == "json"
            else render_markdown(report)
        )
        if args.output is None:
            print(body, end="")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(body, encoding="utf-8")
        return 1 if report["summary"]["expectation_failures"] else 0
    except (OSError, ValueError, ValidationError) as error:
        print(f"冻结回放失败: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())