"""Isolated, network-free validation of the frozen replay evaluator."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from aifreeradar import replay_eval, research_planning
from aifreeradar.replay_eval import (
    DEFAULT_CASES,
    evaluate_replay,
    load_replay_cases,
    main,
)


def cases_by_id() -> dict[str, replay_eval.ReplayCase]:
    return {case.id: case for case in load_replay_cases(DEFAULT_CASES)}


def test_replay_uses_runtime_planner_and_shared_predicates() -> None:
    assert replay_eval.plan_gap_queries is research_planning.plan_gap_queries
    assert replay_eval.evaluate_gap_outcome is research_planning.evaluate_gap_outcome
    assert replay_eval.evaluate_quota_fact is research_planning.evaluate_quota_fact
    assert replay_eval.evaluate_model_deployment is research_planning.evaluate_model_deployment


def test_shipped_fixtures_meet_curated_expectations() -> None:
    report = evaluate_replay(load_replay_cases(DEFAULT_CASES))
    assert report["network_used"] is False
    assert report["summary"]["expectation_failures"] == 0
    assert not [failure for case in report["cases"] for failure in case["expectation_failures"]]
    alias = next(case for case in report["cases"] if case["id"] == "alias-credit-wording")
    assert alias["added_target_ids"] == ["kinetic-free-tier"]
    assert alias["stop_reasons"] == ["gap_resolved"]
    assert alias["missing_target_ids"] == []


def test_recall_requires_evidence_not_returned_list_length() -> None:
    case = cases_by_id()["catalog-zero-price"]
    result = replay_eval.evaluate_case(case)
    metrics = result["metrics"]
    assert metrics["baseline_targets"] == metrics["final_targets"] == 0
    assert result["missing_target_ids"] == ["foo-embed-free"]
    claims = result["field_claim_results"]
    assert claims[0]["accepted"] is True
    rejected = next(claim for claim in claims if not claim["accepted"])
    assert "观察来源" in rejected["reason"]
    assert metrics["unknown_preservation_violations"] == 0


def test_budget_exhaustion_and_provider_failure_do_not_add_recall() -> None:
    fixtures = cases_by_id()
    exhausted = replay_eval.evaluate_case(fixtures["budget-exhausted"])
    assert exhausted["stop_reasons"] == ["budget_exhausted", "budget_exhausted"]
    assert exhausted["metrics"]["additional_requests"] == 0
    assert exhausted["metrics"]["added_targets"] == 0
    assert exhausted["metrics"]["budget_violations"] == 0

    failed = replay_eval.evaluate_case(fixtures["provider-failed"])
    assert failed["stop_reasons"] == ["provider_failed"]
    assert failed["metrics"]["added_targets"] == 0
    assert failed["metrics"]["false_resolved_gaps"] == 0


def test_repeated_source_and_same_guid_do_not_duplicate_queries() -> None:
    fixtures = cases_by_id()
    repeated = replay_eval.evaluate_case(fixtures["repeated-source-dedup"])
    assert repeated["planned_gap_count"] == 1
    assert repeated["metrics"]["duplicate_queries"] == 0
    assert repeated["metrics"]["added_targets"] == 0
    assert repeated["metrics"]["requests_per_added_target"] is None

    revision = fixtures["same-guid-revision"]
    assert [row.revision for row in revision.observations] == [1, 2]
    revised = replay_eval.evaluate_case(revision)
    assert revised["planned_gap_count"] == 1
    assert revised["metrics"]["baseline_targets"] == 1
    assert revised["metrics"]["added_targets"] == 0


def test_forged_captured_trace_is_not_a_resolution() -> None:
    case = cases_by_id()["alias-credit-wording"]
    forged = case.model_copy(update={
        "captured_traces": [{
            "query": "forged query",
            "trigger_url": "https://community.example.org/kinetic-note",
            "stop_reason": "gap_resolved",
            "new_evidence_urls": ["https://forged.example/pricing"],
            "search_calls": 1,
        }]
    })
    result = replay_eval.evaluate_case(forged)
    assert result["captured_metrics"]["false_resolved_gaps"] == 1
    assert result["captured_metrics"]["fetch_budget_observable"] is False
    assert result["captured_metrics"]["fetch_calls"] is None


def test_duplicate_captured_queries_are_measured() -> None:
    case = cases_by_id()["alias-credit-wording"]
    trace = {
        "query": "same generated query",
        "trigger_url": "https://community.example.org/kinetic-note",
        "stop_reason": "no_new_evidence",
        "new_evidence_urls": [],
        "search_calls": 1,
    }
    captured = case.model_copy(update={"captured_traces": [trace, dict(trace)]})
    result = replay_eval.evaluate_case(captured)
    assert result["captured_metrics"]["duplicate_queries"] == 1
    assert result["captured_metrics"]["duplicate_query_rate"] == 0.5


def test_replay_never_opens_a_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("replay must not use the network")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    report = evaluate_replay(load_replay_cases(DEFAULT_CASES))
    assert report["summary"]["added_targets"] > 0


def test_cli_json_and_markdown_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--cases", str(DEFAULT_CASES), "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["field_evidence_support"] == 0.75

    destination = tmp_path / "replay.md"
    assert main([
        "--cases", str(DEFAULT_CASES), "--format", "markdown", "--output", str(destination),
    ]) == 0
    markdown = destination.read_text(encoding="utf-8")
    assert "有限冻结样本" in markdown
    assert "返回列表长度不计作召回" in markdown


def test_invalid_case_is_rejected(tmp_path: Path) -> None:
    base = {
        "id": "broken",
        "category": "text",
        "observations": [{"url": "https://example.org/a", "snippet": "free credits"}],
        "expected_targets": [{
            "id": "target", "urls": ["https://example.org/a"], "evidence_phrases": ["free credits"],
        }],
        "expected_gaps": [{"trigger_url": "https://example.org/a", "target_ids": ["missing"]}],
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"schema_version": 1, "cases": [base]}), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown target ID"):
        load_replay_cases(path)

    base["expected_gaps"] = []
    base["required_unknowns"] = ["not_a_fact_field"]
    path.write_text(json.dumps({"schema_version": 1, "cases": [base]}), encoding="utf-8")
    with pytest.raises(ValueError, match="required_unknowns"):
        load_replay_cases(path)
    base["required_unknowns"] = []
    duplicated = {"schema_version": 1, "cases": [base, {**base}]}
    path.write_text(json.dumps(duplicated), encoding="utf-8")
    with pytest.raises(ValueError, match="distinct"):
        load_replay_cases(path)