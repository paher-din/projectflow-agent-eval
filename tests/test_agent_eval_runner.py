"""Integration tests for agent_eval runner module."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.llm_client import MockLLMClient
from app.agent_eval.case_loader import load_case
from app.agent_eval.runner import (
    _build_parser,
    _cmd_compare,
    _get_entrypoint_from_case,
    _mock_agent_output,
    run_case,
    run_suite,
)
from app.agent_eval.schemas import SemanticGuardMode


# ---------------------------------------------------------------------------
# Tests for mock agent output
# ---------------------------------------------------------------------------


class TestMockAgentOutput:
    def test_all_entrypoints_have_mock(self):
        """Every known entrypoint should have a mock output."""
        for ep in ["clarify", "plan", "breakdown", "recommend-assignments",
                    "negotiate", "active-push", "analyze-risk", "replan"]:
            output = _mock_agent_output(ep)
            assert isinstance(output, dict), f"No mock output for {ep}"
            if ep == "clarify":
                assert "problem" in output

    def test_unknown_entrypoint_returns_default(self):
        output = _mock_agent_output("unknown-module")
        assert output == {"reason": "Mock output", "requires_confirmation": False}

    def test_mock_clarify_has_required_fields(self):
        output = _mock_agent_output("clarify")
        assert "problem" in output
        assert "users" in output
        assert "value" in output
        assert "deliverables" in output

    def test_mock_plan_has_stages(self):
        output = _mock_agent_output("plan")
        assert "stages" in output
        assert len(output["stages"]) >= 2

    def test_mock_negotiate_has_message_and_options(self):
        output = _mock_agent_output("negotiate")
        assert "message" in output
        assert "options" in output


# ---------------------------------------------------------------------------
# Tests for entrypoint mapping
# ---------------------------------------------------------------------------


class TestEntrypointMapping:
    def test_direct_mapping(self):
        class FakeCase:
            entrypoint = "clarify"
        assert _get_entrypoint_from_case(FakeCase()) == "clarify"

    def test_plan_mapping(self):
        class FakeCase:
            entrypoint = "plan"
        assert _get_entrypoint_from_case(FakeCase()) == "plan"

    def test_negotiate_mapping(self):
        class FakeCase:
            entrypoint = "negotiate"
        assert _get_entrypoint_from_case(FakeCase()) == "negotiate"

    def test_unknown_mapping(self):
        class FakeCase:
            entrypoint = "foobar"
        assert _get_entrypoint_from_case(FakeCase()) == "foobar"


# ---------------------------------------------------------------------------
# Tests for run_case
# ---------------------------------------------------------------------------


class TestRunCase:
    def test_mock_mode_returns_report(self):
        """run_case in mock mode should always return a CaseReport."""
        from app.agent_eval.schemas import Assertion, EvalCase, RubricWeights

        case = EvalCase(
            id="test_single",
            title="Single test",
            module="clarification",
            entrypoint="clarify",
            workspace_state={
                "workspace_id": "ws-1",
                "workspace_name": "Test",
                "current_date": "2026-06-05",
                "current_datetime": "2026-06-05T10:00:00+08:00",
                "timezone": "Asia/Shanghai",
                "members": [],
                "project": None,
            },
            expected_behavior=["test"],
            forbidden_behavior=[],
            rubric_weights=RubricWeights(context_grounding=0.5, mvp_boundary=0.3, actionability=0.2),
            minimum_score=0.8,
            hard_fail_rules=[],
            assertions=[
                Assertion(
                    id="has_reason",
                    severity="info",
                    evaluator="deterministic_text",
                    rule="required_terms_present",
                    required=["reason"],
                )
            ],
        )
        report = run_case(case, mode="mock")
        assert report.case_id == "test_single"
        assert report.module == "clarification"
        assert report.agent_status == "success"
        assert isinstance(report.overall_score, float)
        assert report.output_path == ""  # set by caller

    def test_fallback_bad_json_case(self):
        """The fallback_bad_json case should trigger fallback in mock mode."""
        from app.agent_eval.schemas import Assertion, EvalCase, RubricWeights

        case = EvalCase(
            id="fallback_bad_json",
            title="Fallback test",
            module="reliability",
            entrypoint="clarify",
            workspace_state={
                "workspace_id": "ws-1", "workspace_name": "Test",
                "current_date": "2026-06-05", "current_datetime": "2026-06-05T10:00:00+08:00",
                "timezone": "Asia/Shanghai",
                "members": [],
                "project": None,
            },
            expected_behavior=["test"],
            forbidden_behavior=[],
            rubric_weights=RubricWeights(reliability=0.5, mvp_boundary=0.3, context_grounding=0.2),
            minimum_score=0.8,
            hard_fail_rules=["empty_fallback", "unlabeled_fallback"],
        )
        report = run_case(case, mode="mock")
        assert report.used_fallback
        assert report.agent_status == "fallback"
        # Fallback should be valid (non-empty, Chinese)
        assert report.validator_result is not None
        empty_fallback_finding = None
        for f in report.validator_result.findings:
            if f.rule_id == "empty_fallback":
                empty_fallback_finding = f
                break
        assert empty_fallback_finding is not None
        assert empty_fallback_finding.passed  # mock fallback is valid

    def test_real_mode_invokes_agent_flow_with_supplied_llm_client(self):
        """Real mode should call the existing Agent flow without product persistence."""
        from app.agent_eval.schemas import EvalCase, RubricWeights

        case = EvalCase(
            id="real_clarify",
            title="Real clarify",
            module="clarification",
            entrypoint="clarify",
            workspace_state={
                "workspace_id": "ws-1",
                "workspace_name": "Test",
                "current_date": "2026-06-05",
                "current_datetime": "2026-06-05T10:00:00+08:00",
                "timezone": "Asia/Shanghai",
                "members": [],
                "project": {
                    "id": "project-1",
                    "name": "学习规划助手",
                    "idea": "帮助学生拆解学习目标",
                    "deadline": "2026-06-30",
                    "deliverables": "Web MVP",
                    "status": "active",
                    "current_stage_id": None,
                    "stages": [],
                    "tasks": [],
                    "resources": [],
                },
            },
            expected_behavior=["调用真实 Agent flow"],
            forbidden_behavior=[],
            rubric_weights=RubricWeights(context_grounding=0.4, mvp_boundary=0.3, actionability=0.3),
            minimum_score=0.8,
            hard_fail_rules=["invalid_schema", "missing_status"],
        )
        agent_payload = {
            "problem": "学生学习目标难以拆解。",
            "users": "在校学生。",
            "value": "把目标拆成可执行计划。",
            "deliverables": ["方向卡"],
            "boundaries": ["只做 Web MVP"],
            "risks": ["范围过大"],
            "suggested_questions": ["第一版服务哪类学生？"],
            "requires_confirmation": True,
            "reason": "基于 WorkspaceState 生成方向卡。",
        }
        judge_payload = {
            "overall_score": 0.9,
            "passed": True,
            "dimension_scores": {
                "context_grounding": 0.9,
                "mvp_boundary": 0.9,
                "actionability": 0.9,
            },
            "failure_categories": [],
            "strengths": ["调用了真实 Agent flow"],
            "issues": [],
            "evidence": ["Agent output passed DirectionCardOutput validation"],
        }
        client = MockLLMClient(responses=[
            json.dumps(agent_payload, ensure_ascii=False),
            json.dumps(judge_payload, ensure_ascii=False),
        ])

        report = run_case(case, mode="real", llm_client=client, model="real-test")

        assert client.calls == 2
        assert report.agent_status == "success"
        assert report.used_fallback is False
        assert report.overall_score == 0.9
        assert report.status == "passed"
        assert report.error_message == ""

    def test_real_mode_stub_judge_avoids_second_llm_call(self):
        """judge_mode=stub should evaluate quality without calling the LLM judge."""
        from app.agent_eval.schemas import EvalCase, RubricWeights

        case = EvalCase(
            id="real_clarify",
            title="Real clarify",
            module="clarification",
            entrypoint="clarify",
            workspace_state={
                "workspace_id": "ws-1",
                "workspace_name": "Test",
                "current_date": "2026-06-05",
                "current_datetime": "2026-06-05T10:00:00+08:00",
                "timezone": "Asia/Shanghai",
                "members": [],
                "project": {
                    "id": "project-1",
                    "name": "学习规划助手",
                    "idea": "帮助学生拆解学习目标",
                    "deadline": "2026-06-30",
                    "deliverables": "Web MVP",
                    "status": "active",
                    "current_stage_id": None,
                    "stages": [],
                    "tasks": [],
                    "resources": [],
                },
            },
            expected_behavior=["调用真实 Agent flow"],
            forbidden_behavior=[],
            rubric_weights=RubricWeights(context_grounding=0.4, mvp_boundary=0.3, actionability=0.3),
            minimum_score=0.8,
            hard_fail_rules=["invalid_schema", "missing_status"],
        )
        agent_payload = {
            "problem": "学生学习目标难以拆解。",
            "users": "在校学生。",
            "value": "把目标拆成可执行计划。",
            "deliverables": ["方向卡"],
            "boundaries": ["只做 Web MVP"],
            "risks": ["范围过大"],
            "suggested_questions": ["第一版服务哪类学生？"],
            "requires_confirmation": True,
            "reason": "基于 WorkspaceState 生成方向卡。",
        }
        client = MockLLMClient(responses=[json.dumps(agent_payload, ensure_ascii=False)])

        report = run_case(case, mode="real", llm_client=client, model="real-test", judge_mode="stub")

        assert client.calls == 1
        assert report.judge_result is not None
        assert report.judge_result.evidence == ["Stub judge: no evidence reference"]
        assert report.status == "passed"

    def test_real_mode_auto_judge_skips_when_assertions_are_deterministic(self):
        """judge_mode=auto should not spend a second LLM call for deterministic v2 cases."""
        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        case = load_case(fixtures_dir / "clarify_sparse_project.json")
        client = MockLLMClient(
            responses=[json.dumps(_mock_agent_output("clarify"), ensure_ascii=False)]
        )

        report = run_case(case, mode="real", llm_client=client, model="real-test", judge_mode="auto")

        assert client.calls == 1
        assert report.judge_result is not None
        assert report.judge_result.evidence == ["Judge skipped: deterministic assertions covered this case."]
        assert report.status == "passed"

    def test_real_mode_reuses_cached_agent_output_without_llm_call(self):
        """Agent output cache should avoid repeating the expensive real Agent LLM call."""
        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        case = load_case(fixtures_dir / "clarify_sparse_project.json")
        cache_context = {"source_hash": "stable-test-source"}

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            first_client = MockLLMClient(
                responses=[json.dumps(_mock_agent_output("clarify"), ensure_ascii=False)]
            )
            first = run_case(
                case,
                mode="real",
                llm_client=first_client,
                model="real-test",
                judge_mode="auto",
                cache_dir=cache_dir,
                use_cache=True,
                cache_context=cache_context,
            )

            second_client = MockLLMClient(
                responses=[json.dumps({"unused": True}, ensure_ascii=False)]
            )
            second = run_case(
                case,
                mode="real",
                llm_client=second_client,
                model="real-test",
                judge_mode="auto",
                cache_dir=cache_dir,
                use_cache=True,
                cache_context=cache_context,
            )

        assert first_client.calls == 1
        assert second_client.calls == 0
        assert first.cache_hit is False
        assert second.cache_hit is True
        assert second.agent_output == first.agent_output

    def test_semantic_guard_hard_failure_forces_case_failure(self, monkeypatch):
        from app.agent_eval.schemas import Assertion, EvalCase, RubricWeights

        case = EvalCase(
            id="semantic_scope_case",
            title="Semantic scope case",
            module="planning",
            entrypoint="custom-entrypoint",
            workspace_state={
                "workspace_id": "ws-1",
                "workspace_name": "Test",
                "current_date": "2026-06-05",
                "current_datetime": "2026-06-05T10:00:00+08:00",
                "timezone": "Asia/Shanghai",
                "members": [],
                "project": {"id": "project-1", "tasks": []},
            },
            expected_behavior=["test"],
            forbidden_behavior=[],
            rubric_weights=RubricWeights(mvp_boundary=1.0),
            minimum_score=0.8,
            hard_fail_rules=[],
            assertions=[
                Assertion(
                    id="has_reason",
                    severity="info",
                    evaluator="deterministic_text",
                    rule="required_terms_present",
                    required=["reason"],
                )
            ],
        )
        monkeypatch.setattr(
            "app.agent_eval.runner._mock_agent_output",
            lambda entrypoint: {"reason": "MVP 必须交付 Electron 桌面客户端"},
        )

        report = run_case(case, mode="mock", semantic_guard_mode=SemanticGuardMode.auto)

        assert report.status.value == "failed"
        assert "semantic_scope_failure" in report.hard_failures
        assert "scope_creep" in report.failure_categories
        assert report.overall_score == 0.0

    def test_semantic_guard_judge_unavailable_diagnostic_does_not_fail_agent_quality(self, monkeypatch):
        from app.agent_eval.schemas import Assertion, EvalCase, RubricWeights

        case = EvalCase(
            id="semantic_uncertain_case",
            title="Semantic uncertain case",
            module="assignment",
            entrypoint="custom-entrypoint",
            workspace_state={
                "workspace_id": "ws-1",
                "workspace_name": "Test",
                "current_date": "2026-06-05",
                "current_datetime": "2026-06-05T10:00:00+08:00",
                "timezone": "Asia/Shanghai",
                "members": [],
                "project": {"id": "project-1", "tasks": []},
            },
            expected_behavior=["test"],
            forbidden_behavior=[],
            rubric_weights=RubricWeights(context_grounding=1.0),
            minimum_score=0.8,
            hard_fail_rules=[],
            assertions=[
                Assertion(
                    id="has_reason",
                    severity="info",
                    evaluator="deterministic_text",
                    rule="required_terms_present",
                    required=["reason"],
                )
            ],
        )
        monkeypatch.setattr(
            "app.agent_eval.runner._mock_agent_output",
            lambda entrypoint: {"reason": "建议由张三负责后端 API"},
        )

        report = run_case(case, mode="mock", semantic_guard_mode=SemanticGuardMode.auto)

        assert report.status.value == "passed"
        assert report.semantic_guard is not None
        assert report.semantic_guard.hard_failures == []
        assert report.semantic_guard.uncertain_count == 0
        assert report.semantic_guard.findings == []
        assert len(report.semantic_guard.diagnostics) == 1
        assert report.semantic_guard.diagnostics[0].kind.value == "judge_unavailable"

    def test_validator_failure_category_mapping_is_not_always_schema(self, monkeypatch):
        from app.agent_eval.schemas import Assertion, EvalCase, RubricWeights

        case = EvalCase(
            id="validator_scope_case",
            title="Validator scope case",
            module="planning",
            entrypoint="custom-entrypoint",
            workspace_state={
                "workspace_id": "ws-1",
                "workspace_name": "Test",
                "current_date": "2026-06-05",
                "current_datetime": "2026-06-05T10:00:00+08:00",
                "timezone": "Asia/Shanghai",
                "members": [],
                "project": {"id": "project-1", "tasks": []},
            },
            expected_behavior=["test"],
            forbidden_behavior=[],
            rubric_weights=RubricWeights(mvp_boundary=1.0),
            minimum_score=0.8,
            hard_fail_rules=["violates_mvp_boundary"],
            assertions=[
                Assertion(
                    id="has_reason",
                    severity="info",
                    evaluator="deterministic_text",
                    rule="required_terms_present",
                    required=["reason"],
                )
            ],
        )
        monkeypatch.setattr(
            "app.agent_eval.runner._mock_agent_output",
            lambda entrypoint: {"reason": "MVP 必须交付 Electron 桌面客户端"},
        )

        report = run_case(case, mode="mock", semantic_guard_mode=SemanticGuardMode.off)

        assert report.status.value == "failed"
        assert "scope_creep" in report.failure_categories
        assert "schema_failure" not in report.failure_categories

    def test_known_task_id_claimed_fabricated_by_llm_judge_is_downgraded(self):
        from app.agent_eval.schemas import Assertion, EvalCase, RubricWeights

        agent_output = {
            "reason": "根据 check-in blocker 识别风险",
            "requires_confirmation": True,
            "risks": [
                {
                    "type": "workload",
                    "severity": "medium",
                    "title": "task-3 后端任务挤压风险",
                    "description": "task-3 由小林负责，会和 task-1 的 blocker 抢时间。",
                    "evidence": ["task-3 尚未开始，截止日期为 2026-06-25"],
                    "recommendation": "压缩 task-3 范围或调整负责人。",
                    "task_id": "task-3",
                }
            ],
        }
        judge_response = {
            "overall_score": 0.75,
            "passed": False,
            "dimension_scores": {"context_grounding": 0.7},
            "failure_categories": ["fabricated_entity"],
            "strengths": ["识别了 workload 风险"],
            "issues": ["task-3 is fabricated; only task-1 and task-2 are present."],
            "evidence": ["The output references task-3."],
        }
        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        case = load_case(fixtures_dir / "risk_checkin_blocker.json")
        client = MockLLMClient(
            responses=[
                json.dumps(agent_output, ensure_ascii=False),
                json.dumps(judge_response, ensure_ascii=False),
            ]
        )

        report = run_case(
            case,
            mode="real",
            llm_client=client,
            model="real-test",
            judge_mode="llm",
            semantic_guard_mode=SemanticGuardMode.off,
        )

        assert report.status == "passed"
        assert report.judge_result is not None
        assert report.judge_result.passed is True
        assert "fabricated_entity" not in report.failure_categories
        assert "fabricated_entity" not in report.judge_result.failure_categories
        assert len(report.judge_result.diagnostics) == 1
        assert report.judge_result.diagnostics[0].kind.value == "judge_state_mismatch"
        assert "workspace_state.project.tasks[2].id" in report.judge_result.diagnostics[0].message


# ---------------------------------------------------------------------------
# Tests for run_suite integration
# ---------------------------------------------------------------------------


class TestRunSuiteIntegration:
    def test_mock_suite_runs_all_cases(self):
        """Running the full fixture suite in mock mode should complete all 12 cases."""
        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")

        # Use a small temp output dir
        with tempfile.TemporaryDirectory() as tmp:
            reports, summary = run_suite(
                str(fixtures_dir),
                mode="mock",
                output_dir=tmp,
                model="stub",
            )
            assert len(reports) == 12
            assert summary.cases_total == 12
            assert summary.cases_passed == 12

    def test_mock_suite_all_status_valid(self):
        """All cases in mock mode should have a non-error status."""
        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")

        with tempfile.TemporaryDirectory() as tmp:
            reports, _ = run_suite(str(fixtures_dir), mode="mock", output_dir=tmp)
            for rep in reports:
                assert rep.status in ("passed", "failed", "judge_failed", "error"), f"Bad status for {rep.case_id}"

    def test_mock_suite_writes_output_files(self):
        """Mock suite should write report JSON files."""
        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")

        with tempfile.TemporaryDirectory() as tmp:
            reports, summary = run_suite(str(fixtures_dir), mode="mock", output_dir=tmp)
            out_dir = Path(tmp)
            # Check that report files were written
            report_files = list(out_dir.glob("*.report.json"))
            assert len(report_files) == 12
            # Check suite summary
            assert (out_dir / "suite_summary.json").exists()
            # Check markdown summary
            assert (out_dir / "summary.md").exists()

    def test_run_suite_filters_cases_by_id(self):
        """case_ids should run a focused subset for fast benchmark iteration."""
        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")

        with tempfile.TemporaryDirectory() as tmp:
            reports, summary = run_suite(
                str(fixtures_dir),
                mode="mock",
                output_dir=tmp,
                model="stub",
                case_ids=["clarify_sparse_project", "plan_scope_control"],
            )

            assert [r.case_id for r in reports] == ["clarify_sparse_project", "plan_scope_control"]
            assert summary.cases_total == 2

    def test_run_suite_retry_failed_from_previous_run(self):
        """retry_failed_from should select only failed cases from an existing run directory."""
        from app.agent_eval.schemas import CaseReport, CaseStatus

        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = root / "previous"
            previous.mkdir()
            failed = CaseReport(
                run_id="previous",
                case_id="clarify_sparse_project",
                module="clarification",
                model="stub",
                status=CaseStatus.failed,
            )
            passed = CaseReport(
                run_id="previous",
                case_id="plan_scope_control",
                module="planning",
                model="stub",
                status=CaseStatus.passed,
            )
            (previous / "clarify_sparse_project.report.json").write_text(
                failed.model_dump_json(),
                encoding="utf-8",
            )
            (previous / "plan_scope_control.report.json").write_text(
                passed.model_dump_json(),
                encoding="utf-8",
            )

            reports, summary = run_suite(
                str(fixtures_dir),
                mode="mock",
                output_dir=root / "candidate",
                model="stub",
                retry_failed_from=previous,
            )

            assert [r.case_id for r in reports] == ["clarify_sparse_project"]
            assert summary.config is not None
            assert summary.config.retry_mode == "failed"

    def test_run_suite_resume_skips_existing_case_reports(self):
        """resume_from should preserve existing reports and run only missing cases."""
        from app.agent_eval.schemas import CaseReport, CaseStatus

        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = root / "previous"
            previous.mkdir()
            existing = CaseReport(
                run_id="previous",
                case_id="clarify_sparse_project",
                module="clarification",
                model="stub",
                status=CaseStatus.passed,
                overall_score=0.91,
            )
            (previous / "clarify_sparse_project.report.json").write_text(
                existing.model_dump_json(),
                encoding="utf-8",
            )

            reports, summary = run_suite(
                str(fixtures_dir),
                mode="mock",
                output_dir=root / "candidate",
                model="stub",
                case_ids=["clarify_sparse_project", "plan_scope_control"],
                resume_from=previous,
            )

            assert [r.case_id for r in reports] == ["clarify_sparse_project", "plan_scope_control"]
            assert reports[0].overall_score == 0.91
            assert summary.skipped_cases == 1

    def test_mock_suite_summary_values(self):
        """Validate summary values from a full mock run."""
        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")

        with tempfile.TemporaryDirectory() as tmp:
            _, summary = run_suite(str(fixtures_dir), mode="mock", output_dir=tmp)
            assert summary.cases_total == 12
            assert 0 <= summary.average_score <= 1.0
            assert summary.duration_seconds >= 0
            assert summary.run_id.startswith("2")  # starts with year digit

    def test_mock_suite_hard_failures(self):
        """Cases with hard fail rules should report them."""
        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")

        with tempfile.TemporaryDirectory() as tmp:
            reports, summary = run_suite(str(fixtures_dir), mode="mock", output_dir=tmp)
            # All mock outputs are valid, so no hard failures expected
            assert summary.hard_failure_count == 0

    def test_no_secrets_in_output(self):
        """Output files should never expose API keys or secrets."""
        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")

        with tempfile.TemporaryDirectory() as tmp:
            run_suite(str(fixtures_dir), mode="mock", output_dir=tmp)
            for fpath in Path(tmp).rglob("*.json"):
                text = fpath.read_text(encoding="utf-8").lower()
                assert "api_key" not in text, f"Secret in {fpath}"
            for fpath in Path(tmp).rglob("*.md"):
                text = fpath.read_text(encoding="utf-8").lower()
                assert "api_key" not in text, f"Secret in {fpath}"

    def test_multi_run_writes_each_run_report_without_overwrite(self):
        """runs_per_case should preserve per-run reports for stability debugging."""
        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")

        with tempfile.TemporaryDirectory() as tmp:
            run_suite(str(fixtures_dir), mode="mock", output_dir=tmp, runs_per_case=3)

            out_dir = Path(tmp)
            per_run_reports = list(out_dir.glob("*/run_*.report.json"))
            per_run_outputs = list(out_dir.glob("*/run_*.output.json"))

            assert len(per_run_reports) == 36
            assert len(per_run_outputs) == 36


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


class TestCLI:
    def test_run_mock_mode(self):
        """CLI run command should work in mock mode."""
        import subprocess
        import sys

        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")

        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "-m", "app.agent_eval.runner", "run",
                 "--fixtures", str(fixtures_dir),
                 "--output-dir", tmp,
                 "--mode", "mock",
                 "--model", "stub"],
                capture_output=True,
                text=True,
                cwd=Path(__file__).resolve().parent.parent,
            )
            assert "12/12 passed" in result.stdout
            assert "fallback_bad_json" in result.stdout
            assert result.returncode == 0

    def test_list_fixtures(self):
        """CLI list-fixtures command should list all 12 fixtures."""
        import subprocess
        import sys

        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")

        result = subprocess.run(
            [sys.executable, "-m", "app.agent_eval.runner", "list-fixtures",
             "--fixtures", str(fixtures_dir)],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        assert result.returncode == 0
        assert "Total: 12" in result.stdout
        # Check for specific fixture IDs
        for fid in ["clarify_sparse_project", "plan_with_current_date", "fallback_bad_json"]:
            assert fid in result.stdout

    def test_run_parser_accepts_judge_mode_and_case_filter(self):
        parser = _build_parser()

        args = parser.parse_args([
            "run",
            "--mode",
            "real",
            "--judge-mode",
            "auto",
            "--case-filter",
            "clarify_sparse_project,plan_scope_control",
            "--semantic-guard",
            "required",
            "--semantic-judge-model",
            "deepseek-v4-flash",
            "--semantic-judge-base-url",
            "https://api.deepseek.com",
            "--cache-dir",
            "output/agent-eval-cache",
            "--no-cache",
            "--resume",
            "output/agent-eval-real",
            "--retry-failed",
            "output/agent-eval-real",
        ])

        assert args.judge_mode == "auto"
        assert args.case_filter == "clarify_sparse_project,plan_scope_control"
        assert args.semantic_guard == "required"
        assert args.semantic_judge_model == "deepseek-v4-flash"
        assert args.semantic_judge_base_url == "https://api.deepseek.com"
        assert args.cache_dir == "output/agent-eval-cache"
        assert args.no_cache is True
        assert args.resume == "output/agent-eval-real"
        assert args.retry_failed == "output/agent-eval-real"

    def test_compare_reads_utf8_case_reports(self):
        """Compare must load UTF-8 case reports with Chinese agent outputs on Windows."""
        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            candidate = root / "candidate"
            diff_dir = root / "diff"

            run_suite(str(fixtures_dir), mode="mock", output_dir=baseline, model="stub")
            run_suite(str(fixtures_dir), mode="mock", output_dir=candidate, model="stub")

            exit_code = _cmd_compare(
                SimpleNamespace(
                    baseline_dir=str(baseline),
                    candidate_dir=str(candidate),
                    output_dir=str(diff_dir),
                )
            )

            diff = json.loads((diff_dir / "diff_report.json").read_text(encoding="utf-8"))
            assert exit_code == 0
            assert diff["cases_compared"] == 12

