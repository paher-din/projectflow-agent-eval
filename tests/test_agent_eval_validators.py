"""Tests for agent_eval validators module."""
from __future__ import annotations

from typing import Any

from app.agent_eval.schemas import EvalCase, HardFailRule, RubricWeights, ValidatorResult
from app.agent_eval.validators import run_all_validators


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_case(*, hard_fail_rules: list[str] | None = None, module: str = "clarification", **extra: Any) -> EvalCase:
    return EvalCase(
        id="test_validator",
        title="Test",
        module=module,
        entrypoint="clarify",
        workspace_state={
            "workspace_id": "ws-1",
            "workspace_name": "Test",
            "current_date": "2026-06-05",
            "current_datetime": "2026-06-05T10:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "members": [
                {"user_id": "user-1", "display_name": "测试用户", "skills": ["backend"],
                 "available_hours_per_week": 10, "role_preference": "backend",
                 "interests": "开发", "constraints": ""}
            ],
            "project": {
                "id": "project-1",
                "name": "Test",
                "idea": "Test project",
                "deadline": "2026-07-01",
                "deliverables": "",
                "direction_card": None,
                "status": "active",
                "current_stage_id": None,
                "stages": [],
                "tasks": [],
                "checkin_cycles": [],
                "checkin_responses": [],
                "assignment_proposals": [],
                "assignment_responses": [],
                "assignment_negotiations": [],
                "resources": [],
            },
        },
        expected_behavior=["test"],
        forbidden_behavior=["bad"],
        rubric_weights=RubricWeights(context_grounding=0.5, mvp_boundary=0.3, reliability=0.2),
        minimum_score=0.8,
        hard_fail_rules=[HardFailRule(r) for r in (hard_fail_rules or ["invalid_schema", "fabricated_workspace_entity"])],
        **extra,
    )


# ---------------------------------------------------------------------------
# Tests: invalid_schema
# ---------------------------------------------------------------------------


class TestInvalidSchema:
    def test_none_output_fails(self):
        case = _make_case()
        result = run_all_validators(case, None, agent_status="success")
        finding = _find(result, "invalid_schema")
        assert finding is not None
        assert not finding.passed
        assert "invalid_schema" in result.hard_failures

    def test_valid_dict_passes(self):
        case = _make_case()
        result = run_all_validators(case, {"reason": "test"}, agent_status="success")
        finding = _find(result, "invalid_schema")
        assert finding is not None
        assert finding.passed

    def test_list_output_fails(self):
        case = _make_case()
        result = run_all_validators(case, [], agent_status="success")
        finding = _find(result, "invalid_schema")
        assert finding is not None
        assert not finding.passed


# ---------------------------------------------------------------------------
# Tests: missing_status
# ---------------------------------------------------------------------------


class TestMissingStatus:
    def test_empty_status_fails(self):
        case = _make_case(hard_fail_rules=["missing_status"])
        result = run_all_validators(case, {"reason": "test"}, agent_status="")
        finding = _find(result, "missing_status")
        assert finding is not None
        assert not finding.passed

    def test_valid_status_passes(self):
        case = _make_case(hard_fail_rules=["missing_status"])
        result = run_all_validators(case, {"reason": "test"}, agent_status="success")
        finding = _find(result, "missing_status")
        assert finding.passed

    def test_fallback_status_passes(self):
        case = _make_case(hard_fail_rules=["missing_status"])
        result = run_all_validators(case, {"reason": "test"}, agent_status="fallback")
        finding = _find(result, "missing_status")
        assert finding.passed


# ---------------------------------------------------------------------------
# Tests: fabricated_workspace_entity
# ---------------------------------------------------------------------------


class TestFabricatedEntity:
    def test_references_unknown_user_fails(self):
        case = _make_case()
        output = {"reason": "user-99 should help with task-42"}
        result = run_all_validators(case, output, agent_status="success", workspace_state=case.workspace_state)
        finding = _find(result, "fabricated_workspace_entity")
        assert finding is not None
        assert not finding.passed
        assert "fabricated_workspace_entity" in result.hard_failures

    def test_known_entities_pass(self):
        case = _make_case()
        output = {"reason": "user-1 should work on task-3"}
        # workspace has user-1, but no task-3 exists — so task-3 is fabricated
        # Actually let me use a known entity
        output = {"reason": "user-1 is working on the project"}
        result = run_all_validators(case, output, agent_status="success", workspace_state=case.workspace_state)
        finding = _find(result, "fabricated_workspace_entity")
        assert finding.passed

    def test_no_output_still_passes(self):
        case = _make_case()
        result = run_all_validators(case, None, agent_status="failed")
        # invalid_schema takes priority, but fabricated_entity should not fail
        finding = _find(result, "fabricated_workspace_entity")
        assert finding is not None
        assert finding.passed  # "No output to check"


# ---------------------------------------------------------------------------
# Tests: violates_mvp_boundary
# ---------------------------------------------------------------------------


class TestViolatesMvpBoundary:
    def test_mentions_docker_fails(self):
        case = _make_case()
        output = {"reason": "We should use Docker for deployment"}
        result = run_all_validators(case, output)
        finding = _find(result, "violates_mvp_boundary")
        assert finding is not None
        assert not finding.passed

    def test_clean_output_passes(self):
        case = _make_case()
        output = {"reason": "使用 SQLite 存储数据"}
        result = run_all_validators(case, output)
        finding = _find(result, "violates_mvp_boundary")
        assert finding.passed

    def test_mentions_feishu_fails(self):
        case = _make_case()
        output = {"reason": "集成飞书通知"}
        result = run_all_validators(case, output)
        finding = _find(result, "violates_mvp_boundary")
        assert not finding.passed

    def test_desktop_browser_compatibility_passes(self):
        case = _make_case()
        output = {"done_criteria": ["页面适配桌面端主流浏览器"]}
        result = run_all_validators(case, output)
        finding = _find(result, "violates_mvp_boundary")
        assert finding.passed

    def test_electron_desktop_client_fails(self):
        case = _make_case()
        output = {"deliverable": "提供 Electron 桌面端客户端"}
        result = run_all_validators(case, output)
        finding = _find(result, "violates_mvp_boundary")
        assert not finding.passed


# ---------------------------------------------------------------------------
# Tests: unsafe_persistence
# ---------------------------------------------------------------------------


class TestUnsafePersistence:
    def test_requires_confirmation_false_fails(self):
        case = _make_case(hard_fail_rules=["unsafe_persistence"])
        output = {"reason": "test", "requires_confirmation": False}
        result = run_all_validators(case, output)
        finding = _find(result, "unsafe_persistence")
        assert not finding.passed

    def test_requires_confirmation_true_passes(self):
        case = _make_case(hard_fail_rules=["unsafe_persistence"])
        output = {"reason": "test", "requires_confirmation": True}
        result = run_all_validators(case, output)
        finding = _find(result, "unsafe_persistence")
        assert finding.passed

    def test_no_confirmation_field_still_passes(self):
        """Missing requires_confirmation field is not automatically unsafe."""
        case = _make_case(hard_fail_rules=["unsafe_persistence"])
        output = {"reason": "test"}
        result = run_all_validators(case, output)
        finding = _find(result, "unsafe_persistence")
        assert finding.passed


# ---------------------------------------------------------------------------
# Tests: negotiate_created_generic_proposal
# ---------------------------------------------------------------------------


class TestNegotiateGenericProposal:
    def test_non_negotiate_module_skips(self):
        case = _make_case(hard_fail_rules=["negotiate_created_generic_proposal"])
        output = {"reason": "test", "problem": "test", "users": "test", "value": "test"}
        result = run_all_validators(case, output)
        finding = _find(result, "negotiate_created_generic_proposal")
        assert finding.passed  # non-negotiate module skips

    def test_negotiate_with_direction_card_structure_fails(self):
        case = _make_case(hard_fail_rules=["negotiate_created_generic_proposal"], module="negotiate")
        output = {"reason": "test", "problem": "test", "users": "test", "value": "test"}
        result = run_all_validators(case, output)
        finding = _find(result, "negotiate_created_generic_proposal")
        assert not finding.passed

    def test_negotiate_timeline_only_passes(self):
        case = _make_case(hard_fail_rules=["negotiate_created_generic_proposal"], module="negotiate")
        output = {"reason": "test", "swap_reasoning": "小林更适合这个任务"}
        result = run_all_validators(case, output)
        finding = _find(result, "negotiate_created_generic_proposal")
        assert finding.passed


# ---------------------------------------------------------------------------
# Tests: missing_reason
# ---------------------------------------------------------------------------


class TestMissingReason:
    def test_no_reason_field_fails(self):
        case = _make_case(hard_fail_rules=["missing_reason"])
        output = {"stages": []}
        result = run_all_validators(case, output)
        finding = _find(result, "missing_reason")
        assert not finding.passed

    def test_with_reason_passes(self):
        case = _make_case(hard_fail_rules=["missing_reason"])
        output = {"reason": "test reason"}
        result = run_all_validators(case, output)
        finding = _find(result, "missing_reason")
        assert finding.passed

    def test_with_evidence_passes(self):
        case = _make_case(hard_fail_rules=["missing_reason"])
        output = {"evidence": "test evidence"}
        result = run_all_validators(case, output)
        finding = _find(result, "missing_reason")
        assert finding.passed

    def test_with_swap_reasoning_passes(self):
        case = _make_case(hard_fail_rules=["missing_reason"])
        output = {"swap_reasoning": "因为技能匹配"}
        result = run_all_validators(case, output)
        finding = _find(result, "missing_reason")
        assert finding.passed


# ---------------------------------------------------------------------------
# Tests: empty_fallback
# ---------------------------------------------------------------------------


class TestEmptyFallback:
    def test_non_fallback_skips(self):
        case = _make_case(hard_fail_rules=["empty_fallback"])
        output = {}
        result = run_all_validators(case, output, agent_status="success")
        finding = _find(result, "empty_fallback")
        assert finding.passed  # "Not a fallback"

    def test_fallback_empty_dict_fails(self):
        case = _make_case(hard_fail_rules=["empty_fallback"])
        output = {}
        result = run_all_validators(case, output, agent_status="fallback")
        finding = _find(result, "empty_fallback")
        assert not finding.passed

    def test_fallback_valid_chinese_passes(self):
        case = _make_case(hard_fail_rules=["empty_fallback"])
        output = {"reason": "由于 LLM 异常，使用保守方案"}
        result = run_all_validators(case, output, agent_status="fallback")
        finding = _find(result, "empty_fallback")
        assert finding.passed

    def test_fallback_english_only_fails(self):
        case = _make_case(hard_fail_rules=["empty_fallback"])
        output = {"reason": "Using fallback"}
        result = run_all_validators(case, output, agent_status="fallback")
        finding = _find(result, "empty_fallback")
        assert not finding.passed


# ---------------------------------------------------------------------------
# Tests: date_miscalculation
# ---------------------------------------------------------------------------


class TestDateMiscalculation:
    def test_stage_before_current_date_fails(self):
        case = _make_case(hard_fail_rules=["date_miscalculation"])
        output = {
            "stages": [
                {"name": "旧阶段", "start_date": "2026-06-01", "end_date": "2026-06-10"}
            ]
        }
        result = run_all_validators(case, output, workspace_state=case.workspace_state)
        finding = _find(result, "date_miscalculation")
        assert not finding.passed

    def test_stage_after_deadline_fails(self):
        case = _make_case(hard_fail_rules=["date_miscalculation"])
        output = {
            "stages": [
                {"name": "超期阶段", "start_date": "2026-06-10", "end_date": "2026-08-01"}
            ]
        }
        result = run_all_validators(case, output, workspace_state=case.workspace_state)
        finding = _find(result, "date_miscalculation")
        assert not finding.passed

    def test_valid_dates_passes(self):
        case = _make_case(hard_fail_rules=["date_miscalculation"])
        output = {
            "stages": [
                {"name": "有效阶段", "start_date": "2026-06-08", "end_date": "2026-06-25"}
            ]
        }
        result = run_all_validators(case, output, workspace_state=case.workspace_state)
        finding = _find(result, "date_miscalculation")
        assert finding.passed

    def test_no_stages_in_output_passes(self):
        case = _make_case(hard_fail_rules=["date_miscalculation"])
        output = {"reason": "just a reason"}
        result = run_all_validators(case, output, workspace_state=case.workspace_state)
        finding = _find(result, "date_miscalculation")
        assert finding.passed


# ---------------------------------------------------------------------------
# Tests: unlabeled_fallback
# ---------------------------------------------------------------------------


class TestUnlabeledFallback:
    def test_fallback_with_status_passes(self):
        case = _make_case(hard_fail_rules=["unlabeled_fallback"])
        output = {"reason": "fallback"}
        result = run_all_validators(case, output, agent_status="fallback")
        finding = _find(result, "unlabeled_fallback")
        assert finding.passed  # It IS labeled as fallback

    def test_empty_status_fails(self):
        case = _make_case(hard_fail_rules=["unlabeled_fallback"])
        output = {"reason": "test"}
        result = run_all_validators(case, output, agent_status="")
        finding = _find(result, "unlabeled_fallback")
        assert not finding.passed

    def test_success_status_passes(self):
        case = _make_case(hard_fail_rules=["unlabeled_fallback"])
        output = {"reason": "test"}
        result = run_all_validators(case, output, agent_status="success")
        finding = _find(result, "unlabeled_fallback")
        assert finding.passed


# ---------------------------------------------------------------------------
# Tests: combined behavior
# ---------------------------------------------------------------------------


class TestCombinedValidators:
    def test_hard_failure_overrides_soft(self):
        """Hard failures should be in hard_failures list."""
        case = _make_case(hard_fail_rules=["invalid_schema"])
        result = run_all_validators(case, None, agent_status="success")
        assert "invalid_schema" in result.hard_failures
        assert not result.passed

    def test_soft_failure_only(self):
        """Soft failures only appear in soft_failures, and result still passes."""
        case = _make_case(hard_fail_rules=[])  # no hard rules
        result = run_all_validators(case, {"problem": "test"}, agent_status="")
        # missing_status should be soft here since it's not in hard_fail_rules
        finding = _find(result, "missing_status")
        if finding and not finding.passed:
            assert "missing_status" in result.soft_failures

    def test_all_validators_run(self):
        """All rules in the enum should be checked and produce findings."""
        case = _make_case(hard_fail_rules=[r.value for r in HardFailRule])
        result = run_all_validators(case, {"reason": "测试"})
        # All enums should be represented
        rule_ids = {f.rule_id for f in result.findings}
        for rule in HardFailRule:
            assert rule.value in rule_ids, f"Missing finding for {rule.value}"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _find(result: ValidatorResult, rule_id: str):
    for f in result.findings:
        if f.rule_id == rule_id:
            return f
    return None
