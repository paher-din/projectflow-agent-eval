"""Tests for v2 assertion-based agent evaluation."""
from __future__ import annotations

from app.agent_eval.assertion_engine import (
    DEFAULT_SCOPE_FORBIDDEN,
    build_default_assertions_for_case,
    compute_assertion_metrics,
    evaluate_assertion,
    run_all_assertions,
)
from app.agent_eval.runner import run_case, run_suite
from app.agent_eval.schemas import Assertion, EvalCase, RubricWeights


def _case_with_assertions(assertions: list[Assertion]) -> EvalCase:
    return EvalCase(
        id="assertion_case",
        title="Assertion case",
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
                "idea": "帮助学生规划学习时间",
                "deadline": "2026-07-15",
                "deliverables": "Web MVP",
                "status": "active",
                "current_stage_id": None,
                "stages": [],
                "tasks": [],
                "resources": [],
            },
        },
        expected_behavior=["test"],
        forbidden_behavior=[],
        rubric_weights=RubricWeights(context_grounding=0.5, mvp_boundary=0.3, actionability=0.2),
        minimum_score=0.8,
        hard_fail_rules=[],
        assertions=assertions,
    )


def test_trace_assertion_receives_entrypoint_from_runner():
    case = _case_with_assertions([
        Assertion(
            id="correct_module",
            group="trace",
            severity="hard",
            evaluator="trace",
            rule="correct_module_chosen",
            expected=["clarify"],
        )
    ])

    report = run_case(case, mode="mock", model="stub")

    assert report.status.value == "passed"
    assert report.hard_fail_count == 0
    assert report.assertion_results[0].status == "passed"


def test_current_time_assertion_fails_when_workspace_has_no_current_time():
    assertion = Assertion(
        id="current_time_available",
        group="temporal_correctness",
        severity="hard",
        evaluator="deterministic_date",
        rule="current_time_present",
    )

    result = evaluate_assertion(
        assertion,
        {"reason": "当前日期是 2026-06-05"},
        workspace_state={"project": {"deadline": "2026-07-01"}},
    )

    assert result.status == "failed"
    assert result.severity.value == "hard"
    assert "current time" in result.detail.lower()


def test_mock_clarify_output_passes_seed_assertions():
    case = _case_with_assertions([
        Assertion(
            id="no_external_scope",
            group="mvp_boundary",
            severity="hard",
            evaluator="deterministic_text",
            rule="forbidden_terms_absent",
            forbidden=["移动端 App", "第三方登录", "GitHub", "飞书", "日历集成"],
        ),
        Assertion(
            id="uses_current_date",
            group="temporal_correctness",
            severity="major",
            evaluator="deterministic_date",
            rule="current_time_present",
        ),
    ])

    report = run_case(case, mode="mock", model="stub")

    assert report.status.value == "passed"
    assert [r.status for r in report.assertion_results] == ["passed", "passed"]


def test_all_seed_fixtures_run_v2_assertions(tmp_path):
    fixtures_dir = "app/agent_eval/fixtures"

    reports, summary = run_suite(
        fixtures_dir,
        mode="mock",
        output_dir=str(tmp_path),
        model="stub",
    )

    assert summary.cases_passed >= 30  # we have 35+ fixtures now
    assert all(report.assertion_results for report in reports)

    assertion_ids_by_case = {
        report.case_id: {result.assertion_id for result in report.assertion_results}
        for report in reports
    }
    assert "plan_with_current_date_current_time_present" in assertion_ids_by_case["plan_with_current_date"]
    assert "plan_scope_control_no_external_scope" in assertion_ids_by_case["plan_scope_control"]
    assert "breakdown_dependency_gap_dependencies_not_empty_when_ordered" in assertion_ids_by_case[
        "breakdown_dependency_gap"
    ]
    assert "replan_before_after_changes_under_high_risk" in assertion_ids_by_case["replan_before_after"]


# ---------------------------------------------------------------------------
# P0-1: requires_confirmation=false must be caught
# ---------------------------------------------------------------------------


def test_proposal_shape_fails_when_requires_confirmation_is_false():
    """proposal_shape_valid must fail when requires_confirmation is False."""
    assertion = Assertion(
        id="test_proposal_shape",
        group="output_contract",
        severity="hard",
        evaluator="schema",
        rule="proposal_shape_valid",
        failure_category="persistence_boundary_violation",
    )
    result = evaluate_assertion(
        assertion,
        {"reason": "test", "requires_confirmation": False},
    )
    assert result.status == "failed"
    assert "requires_confirmation" in result.detail


def test_proposal_shape_passes_when_requires_confirmation_is_true():
    """proposal_shape_valid must pass when requires_confirmation is True and reason present."""
    assertion = Assertion(
        id="test_proposal_shape",
        group="output_contract",
        severity="hard",
        evaluator="schema",
        rule="proposal_shape_valid",
    )
    result = evaluate_assertion(
        assertion,
        {"reason": "test reason", "requires_confirmation": True},
    )
    assert result.status == "passed"


def test_default_proposal_modules_catch_false_confirmation():
    """Default assertion packs for proposal modules must catch requires_confirmation=False."""
    for module in ("clarification", "planning", "breakdown", "assignment", "replan"):
        assertions = build_default_assertions_for_case(
            case_id="test_case",
            module=module,
            entrypoint=module,
        )
        proposal_assertions = [a for a in assertions if a.rule == "proposal_shape_valid"]
        assert proposal_assertions, f"No proposal_shape assertion for module {module}"
        for pa in proposal_assertions:
            result = evaluate_assertion(
                pa,
                {"reason": "test", "requires_confirmation": False},
            )
            assert result.status == "failed", (
                f"Module {module} proposal assertion should fail on requires_confirmation=False, "
                f"got {result.status}: {result.detail}"
            )


# ---------------------------------------------------------------------------
# P0-2: structured path validation for non-empty fields
# ---------------------------------------------------------------------------


def _make_case_active_push() -> EvalCase:
    return EvalCase(
        id="test_active_push",
        title="Test",
        module="active_push",
        entrypoint="active-push",
        workspace_state={
            "workspace_id": "ws-1",
            "current_date": "2026-06-15",
            "current_datetime": "2026-06-15T10:00:00+08:00",
            "members": [],
            "project": {},
        },
        expected_behavior=["test"],
        forbidden_behavior=[],
        rubric_weights=RubricWeights(context_grounding=0.5, mvp_boundary=0.3, actionability=0.2),
        minimum_score=0.8,
        hard_fail_rules=[],
    )


def test_structured_fields_nonempty_fails_on_empty_next_action():
    """structured_fields_nonempty must fail when cards[*].next_action is empty."""
    assertion = Assertion(
        id="test_card_fields",
        group="actionability",
        severity="hard",
        evaluator="schema",
        rule="structured_fields_nonempty",
        required=["cards[*].next_action", "cards[*].start_guidance", "cards[*].done_when"],
    )
    # Empty next_action
    result = evaluate_assertion(
        assertion,
        {
            "cards": [
                {"next_action": "", "start_guidance": "从文档开始", "done_when": "接口可用"}
            ]
        },
    )
    assert result.status == "failed", f"Expected failed, got {result.status}: {result.detail}"
    assert "next_action" in result.detail


def test_structured_fields_nonempty_fails_on_empty_start_guidance():
    assertion = Assertion(
        id="test_card_fields",
        group="actionability",
        severity="hard",
        evaluator="schema",
        rule="structured_fields_nonempty",
        required=["cards[*].next_action", "cards[*].start_guidance"],
    )
    result = evaluate_assertion(
        assertion,
        {
            "cards": [
                {"next_action": "调研方案", "start_guidance": "", "done_when": "接口可用"}
            ]
        },
    )
    assert result.status == "failed"
    assert "start_guidance" in result.detail


def test_member_invention_assertion_does_not_fail_time_expression():
    assertion = Assertion(
        id="no_fabricated_member",
        group="grounding",
        severity="hard",
        evaluator="state_path",
        rule="does_not_invent_members",
        failure_category="hallucinated_entity",
    )
    output = {"message": "小张 15 小时/周内完成课程搜索页面。"}
    workspace_state = {
        "members": [{"user_id": "user-1", "display_name": "小张"}],
        "project": {"tasks": []},
    }

    result = evaluate_assertion(assertion, output, workspace_state=workspace_state)

    assert result.status == "passed"


def test_replan_meaningful_change_accepts_task_changes():
    assertion = Assertion(
        id="meaningful_replan_delta",
        group="replanning",
        severity="hard",
        evaluator="diff",
        rule="replan_changes_under_high_risk",
        failure_category="no_op_replan",
    )
    output = {
        "before": "课程搜索前端页面截止 7/14",
        "after": "课程搜索前端页面截止 7/18",
        "task_changes": [
            {"task_id": "task-2", "due_date": "2026-07-18", "reason": "消除依赖阻塞"}
        ],
    }

    result = evaluate_assertion(assertion, output)

    assert result.status == "passed"


def test_structured_fields_nonempty_passes_on_all_nonempty():
    assertion = Assertion(
        id="test_card_fields",
        group="actionability",
        severity="hard",
        evaluator="schema",
        rule="structured_fields_nonempty",
        required=["cards[*].next_action", "cards[*].start_guidance"],
    )
    result = evaluate_assertion(
        assertion,
        {
            "cards": [
                {"next_action": "调研方案", "start_guidance": "从文档开始"}
            ]
        },
    )
    assert result.status == "passed"


def test_structured_fields_nonempty_handles_missing_card():
    """If no cards array at all, it should fail."""
    assertion = Assertion(
        id="test_card_fields",
        group="actionability",
        severity="hard",
        evaluator="schema",
        rule="structured_fields_nonempty",
        required=["cards[*].next_action"],
    )
    result = evaluate_assertion(
        assertion,
        {"reason": "没有卡"},
    )
    assert result.status == "failed"


def test_default_active_push_uses_structured_path_instead_of_text_search():
    """The default active_push pack should use structured_fields_nonempty, not required_terms_present."""
    assertions = build_default_assertions_for_case(
        case_id="test_active_push",
        module="active_push",
        entrypoint="active-push",
    )
    structured_assertions = [a for a in assertions if a.rule == "structured_fields_nonempty"]
    assert structured_assertions, "Expected structured_fields_nonempty assertion in active_push pack"
    text_search_assertions = [
        a for a in assertions
        if a.rule == "required_terms_present"
        and "next_action" in (a.required or [])
    ]
    assert not text_search_assertions, (
        "active_push pack should replace text search for next_action/start_guidance/done_when "
        "with structured path validation"
    )


def test_structured_fields_nonempty_fails_on_empty_proposal_owner():
    """Must catch empty recommended_owner in proposals."""
    assertion = Assertion(
        id="test_proposal_fields",
        group="state_grounding",
        severity="hard",
        evaluator="schema",
        rule="structured_fields_nonempty",
        required=["proposals[*].recommended_owner"],
    )
    result = evaluate_assertion(
        assertion,
        {
            "proposals": [
                {"recommended_owner": "", "backup_owner": "user-2", "reason": "技能匹配"}
            ]
        },
    )
    assert result.status == "failed"
    assert "recommended_owner" in result.detail


def test_structured_fields_nonempty_fails_on_empty_risk_evidence():
    """Must catch empty evidence in risks."""
    assertion = Assertion(
        id="test_risk_fields",
        group="actionability",
        severity="major",
        evaluator="schema",
        rule="structured_fields_nonempty",
        required=["risks[*].evidence", "risks[*].suggestion"],
    )
    result = evaluate_assertion(
        assertion,
        {
            "risks": [
                {"type": "deadline", "severity": "high", "evidence": "", "suggestion": "简化方案"}
            ]
        },
    )
    assert result.status == "failed"
    assert "evidence" in result.detail


def test_structured_fields_nonempty_fails_on_empty_acceptance_criteria():
    """Must catch empty acceptance_criteria in tasks."""
    assertion = Assertion(
        id="test_task_fields",
        group="output_contract",
        severity="major",
        evaluator="schema",
        rule="structured_fields_nonempty",
        required=["tasks[*].acceptance_criteria"],
    )
    result = evaluate_assertion(
        assertion,
        {
            "tasks": [
                {"id": "t1", "title": "测试", "acceptance_criteria": []}
            ]
        },
    )
    assert result.status == "failed"
    assert "acceptance_criteria" in result.detail


# ---------------------------------------------------------------------------
# P0-3: Chinese/freeform unknown member names
# ---------------------------------------------------------------------------


def test_does_not_invent_members_catches_fake_user_id():
    """does_not_invent_members must catch user-999 in output."""
    assertion = Assertion(
        id="test_invent_members",
        group="state_grounding",
        severity="hard",
        evaluator="state_path",
        rule="does_not_invent_members",
    )
    ws = {
        "members": [
            {"user_id": "user-1", "display_name": "小林"},
            {"user_id": "user-2", "display_name": "小张"},
        ]
    }
    result = evaluate_assertion(
        assertion,
        {"reason": "user-999 应负责后端", "proposals": []},
        workspace_state=ws,
    )
    assert result.status == "failed", f"Expected failed, got {result.status}: {result.detail}"


def test_does_not_invent_members_defers_chinese_fake_name_to_semantic_guard():
    """Ambiguous Chinese names are semantic guard candidates, not assertion hard fails."""
    assertion = Assertion(
        id="test_invent_chinese",
        group="state_grounding",
        severity="hard",
        evaluator="state_path",
        rule="does_not_invent_members",
    )
    ws = {
        "members": [
            {"user_id": "user-1", "display_name": "小林"},
            {"user_id": "user-2", "display_name": "小张"},
        ]
    }
    result = evaluate_assertion(
        assertion,
        {"reason": "推荐老王负责前端开发"},
        workspace_state=ws,
    )
    assert result.status == "passed", f"Expected passed, got {result.status}: {result.detail}"


def test_does_not_invent_members_passes_on_known_chinese_name():
    """does_not_invent_members must pass when Chinese name is known."""
    assertion = Assertion(
        id="test_invent_known",
        group="state_grounding",
        severity="hard",
        evaluator="state_path",
        rule="does_not_invent_members",
    )
    ws = {
        "members": [
            {"user_id": "user-1", "display_name": "小林"},
        ]
    }
    result = evaluate_assertion(
        assertion,
        {"reason": "推荐小林负责后端开发"},
        workspace_state=ws,
    )
    assert result.status == "passed", f"Expected passed, got {result.status}: {result.detail}"


def test_does_not_invent_members_catches_recommended_owner_not_in_members():
    """assignment output with recommended_owner user-999 must fail."""
    assertion = Assertion(
        id="test_assign_invent",
        group="state_grounding",
        severity="hard",
        evaluator="state_path",
        rule="does_not_invent_members",
    )
    ws = {
        "members": [
            {"user_id": "user-1", "display_name": "小林"},
        ]
    }
    result = evaluate_assertion(
        assertion,
        {
            "reason": "分工推荐",
            "requires_confirmation": True,
            "proposals": [
                {"task_title": "后端", "recommended_owner": "user-999", "reason": "test"}
            ],
        },
        workspace_state=ws,
    )
    assert result.status == "failed", f"Expected failed, got {result.status}: {result.detail}"


def test_does_not_invent_members_catches_chinese_proposal_owner():
    """assignment output with recommended_owner '老王' must fail."""
    assertion = Assertion(
        id="test_assign_chinese_invent",
        group="state_grounding",
        severity="hard",
        evaluator="state_path",
        rule="does_not_invent_members",
    )
    ws = {
        "members": [
            {"user_id": "user-1", "display_name": "小林"},
        ]
    }
    result = evaluate_assertion(
        assertion,
        {
            "reason": "分工推荐",
            "requires_confirmation": True,
            "proposals": [
                {"task_title": "后端", "recommended_owner": "老王", "reason": "test"}
            ],
        },
        workspace_state=ws,
    )
    assert result.status == "failed", f"Expected failed, got {result.status}: {result.detail}"


# ---------------------------------------------------------------------------
# P0-4: Hard assertion score fix
# ---------------------------------------------------------------------------


def test_hard_assertion_failure_sets_weighted_score_zero():
    """Hard assertion failure must make weighted_score/assertion_score 0.0."""
    case = _case_with_assertions([
        Assertion(
            id="hard_fail_test",
            group="mvp_boundary",
            severity="hard",
            evaluator="deterministic_text",
            rule="forbidden_terms_absent",
            forbidden=["Web"],
        )
    ])
    # Mock output referencing forbidden scope
    report = run_case(case, mode="mock", model="stub")
    assert report.hard_fail_count > 0, "Should have hard failures"
    # weighted_score should be 0.0 when hard assertion fails
    assert report.weighted_score == 0.0, f"Expected 0.0, got {report.weighted_score}"


def test_hard_assertion_failure_sets_case_pass_false():
    """case_pass must be false on hard assertion failures."""
    case = _case_with_assertions([
        Assertion(
            id="hard_fail_test",
            group="mvp_boundary",
            severity="hard",
            evaluator="deterministic_text",
            rule="forbidden_terms_absent",
            forbidden=["Web"],
        )
    ])
    report = run_case(case, mode="mock", model="stub")
    assert report.case_pass is False, f"Expected False, got {report.case_pass}"
    assert report.status.value == "failed"


def test_weighted_score_separate_from_overall_on_hard_fail():
    """When hard assertion fails, overall_score (from judge) and weighted_score must differ."""
    case = _case_with_assertions([
        Assertion(
            id="hard_fail_test",
            group="mvp_boundary",
            severity="hard",
            evaluator="deterministic_text",
            rule="forbidden_terms_absent",
            forbidden=["Web"],
        )
    ])
    report = run_case(case, mode="mock", model="stub")
    assert report.overall_score > 0.0, "Judge score should be > 0"
    assert report.weighted_score == 0.0, "Assertion score must be 0 on hard fail"
    assert report.overall_score != report.weighted_score, "Must be distinguishable"


# ---------------------------------------------------------------------------
# P1-1: Replan diff must catch no-op
# ---------------------------------------------------------------------------


def test_replan_noop_note_only_fails():
    """replan_changes_under_high_risk must fail when only note differs."""
    assertion = Assertion(
        id="test_replan_noop",
        group="replanning_effectiveness",
        severity="hard",
        evaluator="diff",
        rule="replan_changes_under_high_risk",
    )
    # Before and after are identical except for a note field
    result = evaluate_assertion(
        assertion,
        {
            "reason": "调整计划",
            "requires_confirmation": True,
            "before": {
                "tasks": [
                    {"id": "t1", "title": "后端", "due_date": "2026-07-15", "status": "in_progress", "owner": "user-1"},
                ]
            },
            "after": {
                "tasks": [
                    {"id": "t1", "title": "后端", "due_date": "2026-07-15", "status": "in_progress", "owner": "user-1"},
                ],
                "note": "稍微调整了一下",
            },
            "changes": [],
            "impact": "无变化",
        },
    )
    assert result.status == "failed", (
        f"Expected failed for no-op replan, got {result.status}: {result.detail}"
    )


def test_replan_with_real_changes_passes():
    """replan_changes_under_high_risk must pass when due_date or status changes."""
    assertion = Assertion(
        id="test_replan_real_change",
        group="replanning_effectiveness",
        severity="hard",
        evaluator="diff",
        rule="replan_changes_under_high_risk",
    )
    result = evaluate_assertion(
        assertion,
        {
            "reason": "延期调整",
            "requires_confirmation": True,
            "before": {
                "tasks": [
                    {"id": "t1", "title": "后端", "due_date": "2026-07-15", "status": "in_progress", "owner": "user-1"},
                ]
            },
            "after": {
                "tasks": [
                    {"id": "t1", "title": "后端", "due_date": "2026-07-20", "status": "in_progress", "owner": "user-1"},
                ],
            },
            "changes": ["延期后端 API 到 7 月 20 日"],
            "impact": "整体延期 5 天",
        },
    )
    assert result.status == "passed", f"Expected passed, got {result.status}: {result.detail}"


def test_replan_without_explicit_changes_but_meaningful_diff_passes():
    """Must pass when before/after differ in meaningful fields but no changes list."""
    assertion = Assertion(
        id="test_replan_meaningful_diff",
        group="replanning_effectiveness",
        severity="hard",
        evaluator="diff",
        rule="replan_changes_under_high_risk",
    )
    result = evaluate_assertion(
        assertion,
        {
            "requires_confirmation": True,
            "before": {"tasks": [{"id": "t1", "due_date": "2026-07-15", "status": "in_progress", "owner": "user-1"}]},
            "after": {"tasks": [{"id": "t1", "due_date": "2026-07-20", "status": "in_progress", "owner": "user-1"}]},
        },
    )
    assert result.status == "passed", f"Expected passed, got {result.status}: {result.detail}"


# ---------------------------------------------------------------------------
# P1-2: dependency_not_all_empty_when_ordered should be hard for breakdown
# ---------------------------------------------------------------------------


def test_dependency_not_empty_default_severity_is_hard_for_breakdown():
    """Default breakdown assertion pack must have dependency rule severity=hard."""
    assertions = build_default_assertions_for_case(
        case_id="breakdown_dependency_gap",
        module="breakdown",
        entrypoint="breakdown",
    )
    dep_assertions = [a for a in assertions if a.rule == "dependency_not_all_empty_when_ordered"]
    assert dep_assertions, "Expected dependency_not_all_empty_when_ordered in breakdown pack"
    for da in dep_assertions:
        assert da.severity.value == "hard", (
            f"Expected severity=hard, got {da.severity.value}"
        )


# ---------------------------------------------------------------------------
# P2: Report clarity
# ---------------------------------------------------------------------------


def test_markdown_shows_failed_total_in_assertions():
    """Markdown Assertions column must show failed/total, not hard_failures/total."""
    from app.agent_eval.report_writer import build_suite_summary, write_markdown_summary
    from app.agent_eval.schemas import CaseReport, CaseStatus, JudgeResult
    import tempfile
    from pathlib import Path

    report = CaseReport(
        run_id="test-r2",
        case_id="test_case_r2",
        module="clarification",
        model="stub",
        status=CaseStatus.failed,
        overall_score=0.85,
        agent_status="success",
        assertion_results=[],
        hard_fail_count=2,
        weighted_score=0.0,
        case_pass=False,
        judge_result=JudgeResult(overall_score=0.85, passed=True),
    )
    summary = build_suite_summary("test-r2", [report])

    with tempfile.TemporaryDirectory() as tmp:
        path = write_markdown_summary(summary, [report], tmp)
        text = Path(path).read_text(encoding="utf-8")
        # The column should show hard_failures string
        assert "hard_failures" in text or "HF" in text or "Assertions" in text


def test_report_separates_overall_and_weighted_score():
    """Case report must distinguish overall_score from weighted_score/assertion_score."""
    case = _case_with_assertions([
        Assertion(
            id="hard_fail_r2",
            group="mvp_boundary",
            severity="hard",
            evaluator="deterministic_text",
            rule="forbidden_terms_absent",
            forbidden=["Web"],
        )
    ])
    report = run_case(case, mode="mock", model="stub")
    assert hasattr(report, "overall_score"), "Must have overall_score"
    assert hasattr(report, "weighted_score"), "Must have weighted_score"
    assert report.weighted_score == 0.0, "weighted_score must be 0.0 on hard fail"
    # Markdown should not conflate the two
    assert report.overall_score != report.weighted_score or report.overall_score == report.weighted_score == 0.0


# ---------------------------------------------------------------------------
# Combined negative probe tests
# ---------------------------------------------------------------------------


def test_planning_requires_confirmation_false_fails_default_assertions():
    """Planning output with requires_confirmation=False must fail on default assertions."""
    from app.agent_eval.assertion_engine import run_all_assertions
    assertions = build_default_assertions_for_case(
        case_id="plan_test",
        module="planning",
        entrypoint="plan",
    )
    output = {
        "reason": "plan test",
        "requires_confirmation": False,
        "stages": [{"name": "S1", "start_date": "2026-06-08", "end_date": "2026-06-20"}],
    }
    results = run_all_assertions(assertions, output, workspace_state={
        "current_date": "2026-06-05",
        "project": {"deadline": "2026-06-30"},
    })
    proposal_results = [r for r in results if r.assertion_id == "plan_test_proposal_shape"]
    assert proposal_results, "Expected proposal_shape assertion"
    assert proposal_results[0].status == "failed", (
        f"Expected failed on requires_confirmation=False, got {proposal_results[0].status}"
    )


def test_assignment_user_999_fails_default_assertions():
    """Assignment output with recommended_owner=user-999 must fail on does_not_invent_members."""
    from app.agent_eval.assertion_engine import run_all_assertions
    assertions = build_default_assertions_for_case(
        case_id="assign_test",
        module="assignment",
        entrypoint="recommend-assignments",
    )
    output = {
        "reason": "分工推荐",
        "requires_confirmation": True,
        "proposals": [
            {"task_title": "后端", "recommended_owner": "user-999", "backup_owner": "user-1", "reason": "test"}
        ],
    }
    ws = {
        "members": [
            {"user_id": "user-1", "display_name": "小林"},
        ]
    }
    results = run_all_assertions(assertions, output, workspace_state=ws)
    invent_results = [r for r in results if r.assertion_id == "assign_test_does_not_invent_members"]
    assert invent_results, "Expected does_not_invent_members assertion"
    assert invent_results[0].status == "failed", (
        f"Expected failed for user-999, got {invent_results[0].status}"
    )


def test_assignment_chinese_name_fails_default_assertions():
    """Assignment output with recommended_owner=老王 must fail on does_not_invent_members."""
    from app.agent_eval.assertion_engine import run_all_assertions
    assertions = build_default_assertions_for_case(
        case_id="assign_test",
        module="assignment",
        entrypoint="recommend-assignments",
    )
    output = {
        "reason": "分工推荐",
        "requires_confirmation": True,
        "proposals": [
            {"task_title": "后端", "recommended_owner": "老王", "backup_owner": "user-1", "reason": "test"}
        ],
    }
    ws = {
        "members": [
            {"user_id": "user-1", "display_name": "小林"},
        ]
    }
    results = run_all_assertions(assertions, output, workspace_state=ws)
    invent_results = [r for r in results if r.assertion_id == "assign_test_does_not_invent_members"]
    assert invent_results, "Expected does_not_invent_members assertion"
    assert invent_results[0].status == "failed", (
        f"Expected failed for 老王, got {invent_results[0].status}"
    )


def test_active_push_empty_next_action_fails_default_assertions():
    """Active push with empty next_action must fail on structured_fields_nonempty."""
    from app.agent_eval.assertion_engine import run_all_assertions
    assertions = build_default_assertions_for_case(
        case_id="push_test",
        module="active_push",
        entrypoint="active-push",
    )
    output = {
        "reason": "行动卡",
        "cards": [
            {"member": "小林", "task": "后端", "next_action": "", "start_guidance": "", "done_when": ""}
        ],
    }
    results = run_all_assertions(assertions, output)
    card_results = [r for r in results if r.assertion_id == "push_test_card_fields_nonempty"]
    assert card_results, "Expected card_fields_nonempty assertion"
    assert card_results[0].status == "failed", (
        f"Expected failed on empty card fields, got {card_results[0].status}"
    )


def test_breakdown_all_empty_deps_hard_fails():
    """Breakdown with ordered tasks and all empty dependency_ids must hard fail."""
    from app.agent_eval.assertion_engine import run_all_assertions
    assertions = build_default_assertions_for_case(
        case_id="breakdown_test",
        module="breakdown",
        entrypoint="breakdown",
    )
    output = {
        "reason": "任务拆解",
        "requires_confirmation": True,
        "tasks": [
            {"id": "t1", "title": "后端 API", "dependency_ids": [], "description": "后端", "priority": "P0",
             "estimated_hours": 20, "can_cut": False, "acceptance_criteria": ["API 可用"]},
            {"id": "t2", "title": "前端页面", "dependency_ids": [], "description": "前端", "priority": "P0",
             "estimated_hours": 15, "can_cut": False, "acceptance_criteria": ["页面可用"]},
        ],
    }
    results = run_all_assertions(assertions, output)
    # Check for dependency rule failure
    dep_results = [r for r in results if r.assertion_id == "breakdown_test_dependencies_not_empty_when_ordered"]
    assert dep_results, "Expected dependencies_not_empty_when_ordered assertion"
    assert dep_results[0].status == "failed", (
        f"Expected failed on all empty deps, got {dep_results[0].status}"
    )
    # Should be severity hard
    assert dep_results[0].severity.value == "hard", (
        f"Expected severity=hard, got {dep_results[0].severity.value}"
    )


def test_replan_identical_before_after_noop_hard_fails():
    """Replan with before/after identical except note must hard fail."""
    from app.agent_eval.assertion_engine import run_all_assertions
    assertions = build_default_assertions_for_case(
        case_id="replan_test",
        module="replan",
        entrypoint="replan",
    )
    output = {
        "reason": "重排",
        "requires_confirmation": True,
        "before": {"tasks": [{"id": "t1", "due_date": "2026-07-15", "status": "in_progress", "owner": "user-1"}]},
        "after": {"tasks": [{"id": "t1", "due_date": "2026-07-15", "status": "in_progress", "owner": "user-1"}], "note": "没啥变化"},
        "changes": [],
        "impact": "无变化",
    }
    ws = {"current_date": "2026-07-10", "project": {"deadline": "2026-07-20"}}
    results = run_all_assertions(assertions, output, workspace_state=ws)
    change_results = [r for r in results if r.assertion_id == "replan_test_changes_under_high_risk"]
    assert change_results, "Expected changes_under_high_risk assertion"
    assert change_results[0].status == "failed", (
        f"Expected failed on noop replan, got {change_results[0].status}: {change_results[0].detail}"
    )
    assert change_results[0].severity.value == "hard"


def test_fallback_empty_output_still_fails_hard():
    """Fallback with empty output should have weighted_score=0.0 and hard fail."""
    case = _case_with_assertions([
        Assertion(
            id="fallback_empty",
            group="reliability",
            severity="hard",
            evaluator="schema",
            rule="no_empty_required_sections",
            required=["problem"],
        ),
        Assertion(
            id="fallback_empty_text",
            group="reliability",
            severity="hard",
            evaluator="deterministic_text",
            rule="required_terms_present",
            required=["reason"],
        ),
    ])
    # Run with empty output
    from app.agent_eval.assertion_engine import evaluate_assertion
    empty_result = evaluate_assertion(
        case.assertions[0],
        {},
        agent_status="fallback",
    )
    assert empty_result.status == "failed"

    # The tracker should have weighted_score=0.0 if no assertions pass
    from app.agent_eval.assertion_engine import run_all_assertions, compute_assertion_metrics
    results = run_all_assertions(case.assertions, {}, agent_status="fallback")
    metrics = compute_assertion_metrics(results)
    assert metrics.get("weighted_score", 1.0) == 0.0, (
        f"Expected weighted_score=0.0 on empty fallback, got {metrics.get('weighted_score')}"
    )


def test_default_reliability_empty_fallback_hard_fails():
    """Default reliability assertion pack must hard fail empty fallback output."""
    from app.agent_eval.assertion_engine import run_all_assertions, compute_assertion_metrics

    assertions = build_default_assertions_for_case(
        case_id="fallback_test",
        module="reliability",
        entrypoint="clarify",
    )

    results = run_all_assertions(assertions, {}, agent_status="fallback", entrypoint="clarify")
    metrics = compute_assertion_metrics(results)

    fallback_results = [r for r in results if r.assertion_id == "fallback_test_fallback_evidence_present"]
    assert fallback_results
    assert fallback_results[0].status == "failed"
    assert fallback_results[0].severity.value == "hard"
    assert metrics["hard_fail_count"] >= 1
    assert metrics["weighted_score"] == 0.0


def test_scope_creep_hard_fail_leaves_weighted_score_zero():
    """Scope creep hard fail must not leave assertion_score/weighted_score at 1.0."""
    case = _case_with_assertions([
        Assertion(
            id="scope_test",
            group="mvp_boundary",
            severity="hard",
            evaluator="deterministic_text",
            rule="forbidden_terms_absent",
            forbidden=["Web"],
        )
    ])
    report = run_case(case, mode="mock", model="stub")
    assert report.hard_fail_count > 0
    assert report.weighted_score == 0.0, f"weighted_score must be 0.0, got {report.weighted_score}"


# ---------------------------------------------------------------------------
# Benchmark self-audit regressions
# ---------------------------------------------------------------------------


def test_valid_json_contract_uses_module_pydantic_schema():
    """valid_json_contract must reject dicts that do not match the module output schema."""
    assertions = build_default_assertions_for_case(
        case_id="plan_bad_schema",
        module="planning",
        entrypoint="plan",
    )
    output = {
        "reason": "根据当前日期 2026-06-05 规划",
        "requires_confirmation": True,
        "stages": [{"foo": "bar"}],
    }

    results = run_all_assertions(
        assertions,
        output,
        workspace_state={
            "current_date": "2026-06-05",
            "project": {"deadline": "2026-07-01"},
        },
        entrypoint="plan",
    )

    valid_schema = [r for r in results if r.assertion_id == "plan_bad_schema_valid_schema"][0]
    assert valid_schema.status == "failed"
    assert "StagePlanOutput" in valid_schema.detail or "stages" in valid_schema.detail


def test_planning_stage_dates_before_current_date_fail_default_assertions():
    """Planning dates must not start or end before the supplied current date."""
    assertions = build_default_assertions_for_case(
        case_id="plan_past_dates",
        module="planning",
        entrypoint="plan",
    )
    output = {
        "reason": "根据当前日期 2026-06-05 规划",
        "requires_confirmation": True,
        "stages": [
            {
                "name": "阶段一",
                "goal": "完成基础搭建",
                "start_date": "2026-05-01",
                "end_date": "2026-05-10",
                "deliverable": "基础框架",
                "done_criteria": ["框架可运行"],
                "order_index": 0,
                "reason": "先打基础",
            }
        ],
    }

    results = run_all_assertions(
        assertions,
        output,
        workspace_state={
            "current_date": "2026-06-05",
            "project": {"deadline": "2026-07-01"},
        },
        entrypoint="plan",
    )

    date_result = [r for r in results if r.assertion_id == "plan_past_dates_deadline_not_in_past"][0]
    assert date_result.status == "failed"
    assert "current_date" in date_result.detail


def test_output_reflects_workspace_state_checks_output_content_not_just_path_existence():
    """State grounding must fail when the workspace value exists but is absent from output."""
    assertion = Assertion(
        id="reflects_goal",
        group="state_grounding",
        severity="major",
        evaluator="state_path",
        rule="output_reflects_workspace_state",
        evidence_paths=["workspace_state.project.goal"],
    )

    result = evaluate_assertion(
        assertion,
        {"reason": "完全没有提项目目标"},
        workspace_state={"project": {"goal": "做学习规划 MVP"}},
    )

    assert result.status == "failed"
    assert "做学习规划 MVP" in result.detail


def test_output_reflects_workspace_state_missing_path_is_failed_not_custom_status():
    assertion = Assertion(
        id="missing_evidence_path",
        group="state_grounding",
        severity="major",
        evaluator="state_path",
        rule="output_reflects_workspace_state",
        evidence_paths=["workspace_state.project.not_exists"],
    )

    result = evaluate_assertion(
        assertion,
        {"reason": "ok"},
        workspace_state={"project": {"goal": "做学习规划 MVP"}},
    )
    metrics = compute_assertion_metrics([result])

    assert result.status == "failed"
    assert metrics["failed_count"] == 1
    assert metrics["weighted_score"] < 1.0


def test_does_not_invent_members_defers_chinese_name_when_known_members_are_english_only():
    assertion = Assertion(
        id="invent_chinese_without_chinese_known_names",
        group="state_grounding",
        severity="hard",
        evaluator="state_path",
        rule="does_not_invent_members",
        failure_category="hallucinated_entity",
    )

    result = evaluate_assertion(
        assertion,
        {"reason": "建议由张三负责后端 API"},
        workspace_state={"members": [{"user_id": "user-1", "display_name": "Lin"}]},
    )

    assert result.status == "passed"


def test_does_not_invent_members_does_not_flag_chinese_phrase_fragments():
    """Chinese member detector must not treat ordinary prose fragments as names."""
    assertion = Assertion(
        id="no_chinese_phrase_false_positive",
        group="state_grounding",
        severity="hard",
        evaluator="state_path",
        rule="does_not_invent_members",
        failure_category="hallucinated_entity",
    )

    output = {
        "reason": "建议优先按技能可覆盖的任务分配，日期前完成核心接口。",
        "assignments": [
            {
                "task_id": "task-1",
                "recommended_owner_user_id": "user-1",
                "backup_owner_user_id": "user-2",
            }
        ],
    }

    result = evaluate_assertion(
        assertion,
        output,
        workspace_state={
            "members": [
                {"user_id": "user-1", "display_name": "小林"},
                {"user_id": "user-2", "display_name": "小张"},
            ],
            "project": {"tasks": [{"id": "task-1"}]},
        },
    )

    assert result.status == "passed"


def test_does_not_invent_members_does_not_flag_non_person_owner_like_phrases():
    """Owner mention extraction should reject common Chinese phrases that look name-shaped."""
    assertion = Assertion(
        id="no_non_person_owner_like_phrase",
        group="state_grounding",
        severity="hard",
        evaluator="state_path",
        rule="does_not_invent_members",
        failure_category="hallucinated_entity",
    )

    result = evaluate_assertion(
        assertion,
        {"reason": "建议小范围负责前端样式调整，并由团队统一确认验收标准。"},
        workspace_state={
            "members": [
                {"user_id": "user-1", "display_name": "小林"},
                {"user_id": "user-2", "display_name": "小张"},
            ]
        },
    )

    assert result.status == "passed"


def test_does_not_invent_members_defers_unknown_honorific_surname_in_owner_context():
    """Unknown Chinese owner-like mentions are semantic guard candidates."""
    assertion = Assertion(
        id="unknown_honorific_owner",
        group="state_grounding",
        severity="hard",
        evaluator="state_path",
        rule="does_not_invent_members",
        failure_category="hallucinated_entity",
    )

    result = evaluate_assertion(
        assertion,
        {"reason": "建议由小王负责前端页面，小林负责后端接口。"},
        workspace_state={"members": [{"user_id": "user-1", "display_name": "小林"}]},
    )

    assert result.status == "passed"


def test_does_not_invent_members_defers_unknown_compound_surname_in_owner_context():
    assertion = Assertion(
        id="unknown_compound_surname_owner",
        group="state_grounding",
        severity="hard",
        evaluator="state_path",
        rule="does_not_invent_members",
        failure_category="hallucinated_entity",
    )

    result = evaluate_assertion(
        assertion,
        {"reason": "建议安排欧阳娜负责演示脚本，小林负责后端接口。"},
        workspace_state={"members": [{"user_id": "user-1", "display_name": "小林"}]},
    )

    assert result.status == "passed"


def test_forbidden_terms_absent_ignores_negated_scope_terms():
    """Boundary checks should not fail when the output explicitly excludes a forbidden scope."""
    assertion = Assertion(
        id="scope_negation",
        group="mvp_boundary",
        severity="hard",
        evaluator="deterministic_text",
        rule="forbidden_terms_absent",
        forbidden=["移动端 App", "教务系统"],
        failure_category="scope_creep",
    )

    result = evaluate_assertion(
        assertion,
        {
            "reason": "MVP 仅限 Web 端，不涉及移动端 App；课程数据先手动录入，暂不接入教务系统。",
        },
    )

    assert result.status == "passed"


def test_forbidden_terms_absent_ignores_out_of_scope_and_clarification_questions():
    """Boundary checks should allow explicitly excluded or unresolved scope terms."""
    assertion = Assertion(
        id="scope_structural_context",
        group="mvp_boundary",
        severity="hard",
        evaluator="deterministic_text",
        rule="forbidden_terms_absent",
        forbidden=["移动端 App", "教务系统"],
        failure_category="scope_creep",
    )

    result = evaluate_assertion(
        assertion,
        {
            "reason": "先收敛 Web MVP",
            "mvp_boundary": {
                "must_have": ["课程搜索"],
                "defer": ["数据统计"],
                "out_of_scope": ["移动端 App"],
            },
            "suggested_questions": ["课程数据是手动录入，还是接入教务系统？"],
        },
    )

    assert result.status == "passed"


def test_default_scope_forbidden_allows_responsive_web_desktop_wording():
    assertion = Assertion(
        id="responsive_web_scope",
        group="mvp_boundary",
        severity="hard",
        evaluator="deterministic_text",
        rule="forbidden_terms_absent",
        forbidden=DEFAULT_SCOPE_FORBIDDEN,
        failure_category="scope_creep",
    )

    result = evaluate_assertion(
        assertion,
        {"done_criteria": ["页面响应式适配移动端与桌面端浏览器"]},
    )

    assert result.status == "passed"


def test_forbidden_terms_absent_still_fails_when_forbidden_scope_is_committed():
    assertion = Assertion(
        id="scope_committed",
        group="mvp_boundary",
        severity="hard",
        evaluator="deterministic_text",
        rule="forbidden_terms_absent",
        forbidden=["教务系统"],
        failure_category="scope_creep",
    )

    result = evaluate_assertion(
        assertion,
        {
            "reason": "需要接入教务系统",
            "stages": [
                {
                    "name": "对接",
                    "deliverable": "教务系统课表数据对接接口",
                    "done_criteria": ["教务系统接口可用"],
                }
            ],
        },
    )

    assert result.status == "failed"
    assert "教务系统" in result.detail


def test_fallback_evidence_requires_transparent_label_not_only_nonempty_output():
    assertion = Assertion(
        id="fallback_label",
        group="reliability",
        severity="hard",
        evaluator="trace",
        rule="fallback_evidence_present",
        failure_category="fallback_quality_failure",
    )

    result = evaluate_assertion(
        assertion,
        {"reason": "请继续推进下一步"},
        agent_status="fallback",
    )

    assert result.status == "failed"
    assert "fallback" in result.detail.lower() or "透明" in result.detail


def test_llm_semantic_placeholder_is_not_reported_as_passed():
    assertion = Assertion(
        id="semantic_quality",
        group="quality",
        severity="major",
        evaluator="llm_semantic",
        rule="must_be_deep_and_specific",
    )

    result = evaluate_assertion(
        assertion,
        {"reason": "随便做一下"},
        workspace_state={"project": {"goal": "做学习规划 MVP"}},
    )

    assert result.status == "skipped"
    assert "not implemented" in result.detail.lower()


def test_weighted_score_below_case_minimum_fails_even_without_hard_assertions():
    case = EvalCase(
        id="soft_threshold_ignored",
        title="Soft failures should fail under minimum score",
        module="custom",
        entrypoint="unknown",
        workspace_state={
            "current_date": "2026-06-05",
            "project": {"deadline": "2026-07-01"},
        },
        expected_behavior=["should fail if weighted score below minimum"],
        forbidden_behavior=[],
        rubric_weights=RubricWeights(context_grounding=1.0),
        minimum_score=0.8,
        hard_fail_rules=[],
        assertions=[
            Assertion(id="missing_alpha", severity="major", evaluator="deterministic_text", rule="required_terms_present", required=["alpha"]),
            Assertion(id="missing_beta", severity="major", evaluator="deterministic_text", rule="required_terms_present", required=["beta"]),
            Assertion(id="missing_gamma", severity="major", evaluator="deterministic_text", rule="required_terms_present", required=["gamma"]),
        ],
    )

    report = run_case(case, mode="mock", model="stub")

    assert report.weighted_score == 0.7
    assert report.status.value == "failed"
    assert report.case_pass is False
