"""Tests for agent_eval report_writer module."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.agent_eval.report_writer import (
    build_suite_summary,
    compare_runs,
    write_case_report,
    write_markdown_summary,
    write_suite_summary,
)
from app.agent_eval.schemas import (
    AssertionResult,
    CaseReport,
    CaseStatus,
    DiffReport,
    JudgeResult,
    RunConfig,
    SemanticDecision,
    SemanticFinding,
    SemanticGuardMode,
    SemanticGuardReport,
    SemanticJudgeDiagnostic,
    SemanticJudgeDiagnosticKind,
    SuiteSummary,
    ValidatorResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_output():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _make_report(
    case_id: str = "test_case",
    score: float = 0.85,
    status: CaseStatus = CaseStatus.passed,
    module: str = "clarification",
    **overrides,
) -> CaseReport:
    kwargs = dict(
        run_id="test-run-001",
        case_id=case_id,
        module=module,
        model="test-model",
        status=status,
        hard_failures=[],
        overall_score=score,
        dimension_scores={"context_grounding": 0.9, "mvp_boundary": 0.8},
        failure_categories=[],
        agent_status="success",
        used_fallback=False,
        attempts=1,
        output_path="",
        validator_result=ValidatorResult(),
        judge_result=JudgeResult(
            overall_score=score,
            passed=status == CaseStatus.passed,
        ),
    )
    kwargs.update(overrides)
    return CaseReport(**kwargs)


# ---------------------------------------------------------------------------
# Tests for write_case_report
# ---------------------------------------------------------------------------


class TestWriteCaseReport:
    def test_write_single_report(self, tmp_output):
        report = _make_report()
        path = write_case_report(report, tmp_output)
        assert Path(path).exists()
        assert path.endswith("test_case.report.json")

        # Verify content
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert data["case_id"] == "test_case"
        assert data["overall_score"] == 0.85
        assert data["status"] == "passed"

    def test_missing_report_path(self, tmp_output):
        """Report.output_path should be set after writing."""
        report = _make_report(output_path="")
        path = write_case_report(report, tmp_output)
        assert report.output_path == path

    def test_output_dir_created_automatically(self, tmp_output):
        nested = tmp_output / "subdir" / "nested"
        report = _make_report()
        path = write_case_report(report, nested)
        assert Path(path).parent.exists()


# ---------------------------------------------------------------------------
# Tests for write_suite_summary
# ---------------------------------------------------------------------------


class TestWriteSuiteSummary:
    def test_write_summary(self, tmp_output):
        summary = SuiteSummary(
            run_id="test-run-001",
            model="test-model",
            cases_total=3,
            cases_passed=2,
            cases_failed=1,
            cases_judge_failed=0,
            average_score=0.82,
            hard_failure_count=0,
            top_failure_categories=["weak_actionability"],
            module_scores={"clarification": 0.85},
            config=RunConfig(mode="mock"),
        )
        path = write_suite_summary(summary, tmp_output)
        assert Path(path).exists()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert data["cases_total"] == 3
        assert data["cases_passed"] == 2


# ---------------------------------------------------------------------------
# Tests for build_suite_summary
# ---------------------------------------------------------------------------


class TestBuildSuiteSummary:
    def test_all_passed(self):
        reports = [
            _make_report("c1", 0.9, CaseStatus.passed),
            _make_report("c2", 0.8, CaseStatus.passed),
        ]
        summary = build_suite_summary("run-1", reports, duration_seconds=5.0)
        assert summary.cases_total == 2
        assert summary.cases_passed == 2
        assert summary.cases_failed == 0
        assert summary.average_score == 0.85
        assert summary.duration_seconds == 5.0

    def test_mixed_results(self):
        reports = [
            _make_report("c1", 0.9, CaseStatus.passed),
            _make_report("c2", 0.3, CaseStatus.failed, hard_failures=["invalid_schema"]),
            _make_report("c3", 0.0, CaseStatus.judge_failed),
            _make_report("c4", 0.0, CaseStatus.error, error_message="broken"),
        ]
        summary = build_suite_summary("run-2", reports)
        assert summary.cases_total == 4
        assert summary.cases_passed == 1
        assert summary.cases_failed == 1
        assert summary.cases_judge_failed == 1
        assert summary.hard_failure_count == 1

    def test_module_scores(self):
        reports = [
            _make_report("c1", 0.9, module="clarification"),
            _make_report("c2", 0.7, module="clarification"),
            _make_report("c3", 0.8, module="planning"),
        ]
        summary = build_suite_summary("run-3", reports)
        assert "clarification" in summary.module_scores
        assert "planning" in summary.module_scores
        assert summary.module_scores["clarification"] == 0.8
        assert summary.module_scores["planning"] == 0.8

    def test_top_failure_categories(self):
        reports = [
            _make_report("c1", 0.3, CaseStatus.failed, failure_categories=["schema_failure", "hallucinated_entity"]),
            _make_report("c2", 0.2, CaseStatus.failed, failure_categories=["schema_failure"]),
        ]
        summary = build_suite_summary("run-4", reports)
        assert "schema_failure" in summary.top_failure_categories
        assert "hallucinated_entity" in summary.top_failure_categories

    def test_empty_reports(self):
        summary = build_suite_summary("run-empty", [])
        assert summary.cases_total == 0
        assert summary.average_score == 0.0

    def test_summary_counts_v2_hard_assertions_and_effective_score(self):
        report = _make_report(
            "v2_hard",
            0.85,
            CaseStatus.failed,
            assertion_results=[
                AssertionResult(
                    assertion_id="schema_contract",
                    status="failed",
                    severity="hard",
                    failure_category="schema_failure",
                )
            ],
            hard_fail_count=1,
            weighted_score=0.0,
            case_pass=False,
        )

        summary = build_suite_summary("run-v2-hard", [report])

        assert summary.hard_failure_count == 1
        assert summary.average_score == 0.0
        assert summary.module_scores["clarification"] == 0.0
        assert "schema_failure" in summary.top_failure_categories

    def test_summary_excludes_judge_failed_from_quality_average(self):
        """Judge infrastructure failures should not be scored as agent quality zeroes."""
        reports = [
            _make_report("passed", 0.9, CaseStatus.passed, module="planning"),
            _make_report("judge_down", 0.0, CaseStatus.judge_failed, module="planning"),
        ]

        summary = build_suite_summary("run-judge-down", reports)

        assert summary.cases_total == 2
        assert summary.cases_judge_failed == 1
        assert summary.average_score == 0.9
        assert summary.module_scores["planning"] == 0.9


# ---------------------------------------------------------------------------
# Tests for write_markdown_summary
# ---------------------------------------------------------------------------


class TestWriteMarkdownSummary:
    def test_basic_markdown(self, tmp_output):
        reports = [
            _make_report("c1", 0.9, CaseStatus.passed, module="clarification"),
        ]
        summary = build_suite_summary("run-1", reports)
        path = write_markdown_summary(summary, reports, tmp_output)
        assert Path(path).exists()
        text = Path(path).read_text(encoding="utf-8")
        assert "# Agent Evaluation Benchmark Report" in text
        assert "✅" in text  # pass status
        assert "c1" in text

    def test_markdown_with_failures(self, tmp_output):
        reports = [
            _make_report("c1", 0.9, CaseStatus.passed),
            _make_report("c2", 0.2, CaseStatus.failed, hard_failures=["invalid_schema"]),
        ]
        summary = build_suite_summary("run-2", reports)
        path = write_markdown_summary(summary, reports, tmp_output)
        text = Path(path).read_text(encoding="utf-8")
        assert "❌" in text  # fail icon
        assert "invalid_schema" in text

    def test_markdown_with_baseline(self, tmp_output):
        reports = [_make_report("c1", 0.85, CaseStatus.passed)]
        summary = build_suite_summary("run-3", reports)
        baseline = SuiteSummary(
            run_id="baseline-1", model="old", cases_total=1, cases_passed=1,
            cases_failed=0, cases_judge_failed=0, average_score=0.9,
            hard_failure_count=0,
        )
        path = write_markdown_summary(summary, reports, tmp_output, baseline_summary=baseline)
        text = Path(path).read_text(encoding="utf-8")
        assert "Regression vs Baseline" in text
        assert "Score Delta" in text

    def test_markdown_omits_secrets(self, tmp_output):
        """Verify the report never exposes API keys."""
        reports = [_make_report("c1", 0.85, CaseStatus.passed)]
        config = RunConfig(
            mode="real",
            model="test-model",
            provider="openai-compatible",
            base_url_host="api.example.com",
        )
        summary = build_suite_summary("run-secure", reports, config=config)
        path = write_markdown_summary(summary, reports, tmp_output)
        text = Path(path).read_text(encoding="utf-8")
        assert "api_key" not in text.lower()
        assert "secret" not in text.lower()
        assert "token" not in text.lower()

    def test_markdown_includes_semantic_guard_summary(self, tmp_output):
        semantic_guard = SemanticGuardReport(
            mode=SemanticGuardMode.auto,
            findings=[
                SemanticFinding(
                    kind="scope",
                    span="Electron",
                    path="agent_output.reason",
                    decision=SemanticDecision.fail,
                    confidence=1.0,
                    evidence="Native desktop app commitment.",
                    failure_category="scope_creep",
                    rule_id="semantic_scope_failure",
                    severity="hard",
                )
            ],
            hard_failures=["semantic_scope_failure"],
            failure_categories=["scope_creep"],
        )
        reports = [
            _make_report(
                "semantic_scope",
                0.0,
                CaseStatus.failed,
                hard_failures=["semantic_scope_failure"],
                failure_categories=["scope_creep"],
                semantic_guard=semantic_guard,
            )
        ]
        summary = build_suite_summary("run-semantic", reports)

        path = write_markdown_summary(summary, reports, tmp_output)
        text = Path(path).read_text(encoding="utf-8")

        assert "Semantic Guard" in text
        assert "semantic_scope_failure" in text
        assert "Electron" in text

    def test_markdown_surfaces_semantic_judge_diagnostics_separately(self, tmp_output):
        semantic_guard = SemanticGuardReport(
            mode=SemanticGuardMode.auto,
            called=True,
            diagnostics=[
                SemanticJudgeDiagnostic(
                    kind=SemanticJudgeDiagnosticKind.judge_schema_error,
                    message="Semantic judge response failed validation.",
                    candidate_count=1,
                    case_impact="none",
                    diagnostic_only=True,
                )
            ],
        )
        reports = [
            _make_report(
                "breakdown_dependency_gap",
                0.85,
                CaseStatus.failed,
                failure_categories=["dependency_inconsistency"],
                semantic_guard=semantic_guard,
            )
        ]
        summary = build_suite_summary("run-diagnostics", reports)

        path = write_markdown_summary(summary, reports, tmp_output)
        text = Path(path).read_text(encoding="utf-8")

        assert "Semantic Judge Diagnostics" in text
        assert "judge_schema_error" in text
        assert "dependency_inconsistency" in summary.top_failure_categories
        assert "judge_schema_error" not in summary.top_failure_categories

    def test_markdown_surfaces_main_judge_diagnostics_separately(self, tmp_output):
        reports = [
            _make_report(
                "risk_checkin_blocker",
                0.75,
                CaseStatus.failed,
                failure_categories=["weak_actionability"],
                judge_result=JudgeResult(
                    overall_score=0.75,
                    passed=False,
                    failure_categories=["weak_actionability"],
                    diagnostics=[
                        SemanticJudgeDiagnostic(
                            kind=SemanticJudgeDiagnosticKind.judge_state_mismatch,
                            message=(
                                "Judge claimed task-3 was fabricated but resolver "
                                "found it at workspace_state.project.tasks[2].id."
                            ),
                            case_impact="none",
                            diagnostic_only=True,
                        )
                    ],
                ),
            )
        ]
        summary = build_suite_summary("run-judge-diagnostics", reports)

        path = write_markdown_summary(summary, reports, tmp_output)
        text = Path(path).read_text(encoding="utf-8")

        assert "Judge Diagnostics" in text
        assert "judge_state_mismatch" in text
        assert "workspace_state.project.tasks[2].id" in text
        assert "judge_state_mismatch" not in summary.top_failure_categories


# ---------------------------------------------------------------------------
# Tests for compare_runs
# ---------------------------------------------------------------------------


class TestCompareRuns:
    def test_identical_runs(self):
        base_reports = [_make_report("c1", 0.85, CaseStatus.passed, module="clarification")]
        cand_reports = [_make_report("c1", 0.85, CaseStatus.passed, module="clarification")]
        base_summary = build_suite_summary("base-1", base_reports)
        cand_summary = build_suite_summary("cand-1", cand_reports)

        diff = compare_runs(base_summary, cand_summary, base_reports, cand_reports)
        assert isinstance(diff, DiffReport)
        assert diff.average_score_delta == 0.0
        assert diff.regression_passed
        assert len(diff.entries) == 1

    def test_regression_detected(self):
        base_reports = [_make_report("c1", 0.9, CaseStatus.passed)]
        cand_reports = [_make_report("c1", 0.5, CaseStatus.failed)]
        base_summary = build_suite_summary("base-1", base_reports)
        cand_summary = build_suite_summary("cand-1", cand_reports)

        diff = compare_runs(base_summary, cand_summary, base_reports, cand_reports)
        assert diff.average_score_delta < -0.03
        assert not diff.regression_passed
        assert "c1" in diff.failed_candidates

    def test_new_hard_failures(self):
        base_reports = [_make_report("c1", 0.9, CaseStatus.passed)]
        cand_reports = [_make_report("c1", 0.2, CaseStatus.failed, hard_failures=["invalid_schema"])]
        base_summary = build_suite_summary("base-1", base_reports)
        cand_summary = build_suite_summary("cand-1", cand_reports)

        diff = compare_runs(base_summary, cand_summary, base_reports, cand_reports)
        assert "c1" in diff.new_hard_failures_by_case
        assert not diff.regression_passed

    def test_fixed_hard_failures(self):
        base_reports = [_make_report("c1", 0.2, CaseStatus.failed, hard_failures=["invalid_schema"])]
        cand_reports = [_make_report("c1", 0.9, CaseStatus.passed)]
        base_summary = build_suite_summary("base-1", base_reports)
        cand_summary = build_suite_summary("cand-1", cand_reports)

        diff = compare_runs(base_summary, cand_summary, base_reports, cand_reports)
        assert "c1" in diff.fixed_hard_failures_by_case
        assert diff.regression_passed  # no regression

    def test_missing_case_in_candidate(self):
        base_reports = [
            _make_report("c1", 0.9, CaseStatus.passed),
            _make_report("c2", 0.8, CaseStatus.passed),
        ]
        cand_reports = [_make_report("c1", 0.85, CaseStatus.passed)]
        base_summary = build_suite_summary("base-1", base_reports)
        cand_summary = build_suite_summary("cand-1", cand_reports)

        diff = compare_runs(base_summary, cand_summary, base_reports, cand_reports)
        assert diff.cases_compared == 2  # c2 should still appear

    def test_both_empty(self):
        diff = compare_runs(
            build_suite_summary("base", []),
            build_suite_summary("cand", []),
            [], [],
        )
        assert diff.cases_compared == 0
        assert diff.regression_passed

    def test_v2_hard_assertion_regression_fails_compare(self):
        hard_assertion = AssertionResult(
            assertion_id="schema_contract",
            status="failed",
            severity="hard",
            failure_category="schema_failure",
        )
        base_reports = [
            _make_report("c1", 0.85, CaseStatus.passed, weighted_score=1.0, case_pass=True)
        ]
        cand_reports = [
            _make_report(
                "c1",
                0.85,
                CaseStatus.failed,
                assertion_results=[hard_assertion],
                hard_fail_count=1,
                weighted_score=0.0,
                case_pass=False,
            )
        ]
        base_summary = build_suite_summary("base-v2", base_reports)
        cand_summary = build_suite_summary("cand-v2", cand_reports)

        diff = compare_runs(base_summary, cand_summary, base_reports, cand_reports)

        assert "c1" in diff.new_hard_failures_by_case
        assert "assertion:schema_contract" in diff.new_hard_failures_by_case["c1"]
        assert not diff.regression_passed
