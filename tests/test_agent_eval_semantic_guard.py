"""Tests for AgentEval semantic guard v2.1: schema, candidate extraction, orchestration."""
from __future__ import annotations

from app.agent_eval.schemas import (
    CaseReport,
    CaseStatus,
    SemanticCandidate,
    SemanticCandidateDecision,
    SemanticCandidateSource,
    SemanticDecision,
    SemanticFinding,
    SemanticGuardMode,
    SemanticGuardReport,
    SemanticRisk,
    ScopeCommitmentLevel,
)
from app.agent_eval.semantic_guard import (
    DEFAULT_SCOPE_CONTRACT,
    build_workspace_entity_index,
    extract_entity_candidates,
    extract_scope_candidates,
    resolve_workspace_entity,
    run_semantic_guard,
)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_semantic_guard_report_defaults_are_safe():
    report = SemanticGuardReport(mode=SemanticGuardMode.auto)

    assert report.mode == SemanticGuardMode.auto
    assert report.called is False
    assert report.cache_hit is False
    assert report.duration_seconds == 0.0
    assert report.uncertain_count == 0
    assert report.findings == []
    assert report.hard_failures == []
    assert report.failure_categories == []


def test_semantic_finding_hard_fail_requires_fail_confidence_and_evidence():
    finding = SemanticFinding(
        kind="scope",
        span="教务系统课表对接",
        path="agent_output.stages[0].deliverable",
        decision=SemanticDecision.fail,
        confidence=0.91,
        evidence="The output commits to academic system integration.",
        failure_category="scope_creep",
    )

    assert finding.is_hard_failure is True


def test_semantic_finding_uncertain_is_not_hard_failure():
    finding = SemanticFinding(
        kind="entity",
        span="李想",
        path="agent_output.raw_text",
        decision=SemanticDecision.uncertain,
        confidence=0.62,
        evidence="Could be a person or a phrase in this context.",
        failure_category="hallucinated_entity",
        severity="uncertain",
        source="text_trigger",
        risk="medium",
    )

    assert finding.is_hard_failure is False


def test_semantic_candidate_records_source_risk_and_commitment():
    entity_candidate = SemanticCandidate(
        kind="entity",
        span="周内",
        path="agent_output.raw_text",
        local_context="15 小时/周内完成",
        deterministic_decision=SemanticCandidateDecision.pass_,
        source=SemanticCandidateSource.time_or_range_pattern,
        risk=SemanticRisk.low,
    )
    scope_candidate = SemanticCandidate(
        kind="scope",
        span="桌面端主流浏览器",
        path="agent_output.done_criteria[0]",
        local_context="页面适配桌面端主流浏览器",
        deterministic_decision=SemanticCandidateDecision.pass_,
        source=SemanticCandidateSource.ambiguous_term,
        commitment_level=ScopeCommitmentLevel.compatibility_note,
    )

    assert entity_candidate.source == SemanticCandidateSource.time_or_range_pattern
    assert entity_candidate.risk == SemanticRisk.low
    assert scope_candidate.commitment_level == ScopeCommitmentLevel.compatibility_note


def test_case_report_accepts_semantic_guard_report():
    semantic_report = SemanticGuardReport(
        mode=SemanticGuardMode.off,
        called=False,
    )
    case_report = CaseReport(
        run_id="run-1",
        case_id="case_1",
        module="planning",
        model="stub",
        status=CaseStatus.passed,
        semantic_guard=semantic_report,
    )

    assert case_report.semantic_guard == semantic_report


def test_entity_extractor_marks_time_expression_as_low_risk_pass():
    output = {"message": "小张 15 小时/周内完成课程搜索页面。"}
    workspace_state = {
        "members": [{"user_id": "user-1", "display_name": "小张"}],
        "project": {"tasks": []},
    }

    candidates = extract_entity_candidates(output, workspace_state)

    assert any(c.span == "周内" for c in candidates)
    candidate = next(c for c in candidates if c.span == "周内")
    assert candidate.deterministic_decision == SemanticCandidateDecision.pass_
    assert candidate.source == SemanticCandidateSource.time_or_range_pattern
    assert candidate.risk == SemanticRisk.low


def test_entity_extractor_hard_fails_unknown_id_reference():
    output = {"recommended_owner_user_id": "user-404"}
    workspace_state = {
        "members": [{"user_id": "user-1", "display_name": "小林"}],
        "project": {"tasks": []},
    }

    candidates = extract_entity_candidates(output, workspace_state)

    assert any(
        c.span == "user-404" and c.deterministic_decision == SemanticCandidateDecision.fail
        for c in candidates
    )


def test_entity_extractor_allows_output_defined_task_ids():
    output = {
        "tasks": [
            {"id": "task-1", "title": "后端接口", "dependency_ids": []},
            {"id": "task-2", "title": "前端页面", "dependency_ids": ["task-1"]},
        ],
        "proposal_id": "prop-1",
    }
    workspace_state = {"members": [], "project": {"tasks": []}}

    candidates = extract_entity_candidates(output, workspace_state)

    assert candidates == []


def test_entity_resolver_checks_top_level_and_project_tasks():
    workspace_state = {
        "tasks": [{"id": "task-top", "title": "顶层任务"}],
        "project": {"tasks": [{"id": "task-project", "title": "项目任务"}]},
    }

    index = build_workspace_entity_index(workspace_state)

    top = resolve_workspace_entity("task-top", index)
    project = resolve_workspace_entity("task-project", index)
    missing = resolve_workspace_entity("task-missing", index)

    assert top.exists is True
    assert top.state_path == "workspace_state.tasks[0].id"
    assert project.exists is True
    assert project.state_path == "workspace_state.project.tasks[0].id"
    assert missing.exists is False
    assert missing.entity_type == "task"


def test_entity_extractor_role_phrase_is_not_fabricated_person():
    output = {"reason": "由产品负责人确认后再调整计划"}
    workspace_state = {"members": [{"user_id": "user-1", "display_name": "小林"}], "project": {"tasks": []}}

    candidates = extract_entity_candidates(output, workspace_state)

    assert not any(c.span == "产品负责人" and c.deterministic_decision == SemanticCandidateDecision.fail for c in candidates)


def test_entity_extractor_style_phrase_is_not_real_assignment():
    output = {"reason": "保持王同学风格的任务分配说明，但不新增负责人"}
    workspace_state = {"members": [{"user_id": "user-1", "display_name": "小林"}], "project": {"tasks": []}}

    candidates = extract_entity_candidates(output, workspace_state)

    assert not any(c.span == "王同学" and c.deterministic_decision == SemanticCandidateDecision.fail for c in candidates)


def test_entity_extractor_does_not_send_common_words_to_judge():
    output = {
        "reason": "协作设计完成后，尚未启动的任务需要继续跟进。",
        "description": "功能的列表页面需要优化。",
    }
    workspace_state = {"members": [], "project": {"tasks": []}}

    candidates = extract_entity_candidates(output, workspace_state)

    assert candidates == []


def test_scope_extractor_desktop_browser_is_compatibility_pass():
    output = {"done_criteria": ["页面适配桌面端主流浏览器"]}

    candidates = extract_scope_candidates(output, DEFAULT_SCOPE_CONTRACT)

    assert any(c.span == "桌面端主流浏览器" for c in candidates)
    candidate = next(c for c in candidates if c.span == "桌面端主流浏览器")
    assert candidate.deterministic_decision == SemanticCandidateDecision.pass_
    assert candidate.commitment_level == ScopeCommitmentLevel.compatibility_note


def test_scope_extractor_responsive_desktop_wording_is_compatibility_pass():
    output = {"done_criteria": ["页面响应式适配移动端与桌面端浏览器"]}

    candidates = extract_scope_candidates(output, DEFAULT_SCOPE_CONTRACT)

    assert any(
        c.span == "桌面端" and c.deterministic_decision == SemanticCandidateDecision.pass_
        for c in candidates
    )
    assert not any(c.deterministic_decision == SemanticCandidateDecision.fail for c in candidates)


def test_scope_extractor_splits_ambiguous_mobile_and_desktop_span():
    output = {"done_criteria": ["支持移动端和桌面端使用体验"]}

    candidates = extract_scope_candidates(output, DEFAULT_SCOPE_CONTRACT)

    spans = {c.span for c in candidates}
    assert "移动端" in spans
    assert "桌面端" in spans
    assert all(c.deterministic_decision == SemanticCandidateDecision.ambiguous for c in candidates)


def test_scope_extractor_academic_system_integration_is_fail():
    output = {"deliverable": "实现教务系统课表对接"}

    candidates = extract_scope_candidates(output, DEFAULT_SCOPE_CONTRACT)

    assert any(
        c.span == "教务系统课表对接" and c.deterministic_decision == SemanticCandidateDecision.fail
        for c in candidates
    )


def test_scope_extractor_future_mobile_direction_is_not_hard_fail():
    output = {"mvp_boundary": {"defer": ["后续可探索移动端适配"]}}

    candidates = extract_scope_candidates(output, DEFAULT_SCOPE_CONTRACT)

    assert not any(c.deterministic_decision == SemanticCandidateDecision.fail for c in candidates)


def test_scope_extractor_manual_csv_import_is_not_academic_system_integration():
    output = {"description": "用户可手动导入教务系统导出的课表 CSV"}

    candidates = extract_scope_candidates(output, DEFAULT_SCOPE_CONTRACT)

    assert not any(c.deterministic_decision == SemanticCandidateDecision.fail for c in candidates)


def test_scope_extractor_does_not_send_internal_api_or_deploy_to_judge():
    output = {
        "reason": "后端 API 与前端联调完成后进行 Web 应用部署。",
        "done_criteria": ["核心 API 可用", "应用部署到测试环境"],
    }

    candidates = extract_scope_candidates(output, DEFAULT_SCOPE_CONTRACT)

    assert candidates == []


def test_semantic_guard_off_mode_does_not_call_judge(tmp_path):
    class CountingClient:
        calls = 0

        def complete(self, messages, *, max_tokens=None):
            self.calls += 1
            return '{"findings": []}'

    client = CountingClient()
    report = run_semantic_guard(
        case_id="case_1",
        module="planning",
        agent_output={"done_criteria": ["页面适配桌面端主流浏览器"]},
        workspace_state={"members": [], "project": {"tasks": []}},
        mode=SemanticGuardMode.off,
        judge_client=client,
        cache_dir=tmp_path,
        use_cache=False,
        judge_model="deepseek-v4-flash",
    )

    assert report.called is False
    assert client.calls == 0


def test_semantic_guard_auto_mode_uncertain_when_judge_unavailable(tmp_path):
    class BrokenClient:
        def complete(self, messages, *, max_tokens=None):
            raise RuntimeError("offline")

    report = run_semantic_guard(
        case_id="case_1",
        module="planning",
        agent_output={"description": "后续可考虑外部系统自动同步，但本期不做"},
        workspace_state={"members": [], "project": {"tasks": []}},
        mode=SemanticGuardMode.auto,
        judge_client=BrokenClient(),
        cache_dir=tmp_path,
        use_cache=False,
        judge_model="deepseek-v4-flash",
    )

    assert report.called is True
    assert report.error_message
    assert report.hard_failures == []
    assert report.findings == []
    assert report.failure_categories == []
    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].kind.value == "judge_unavailable"


def test_semantic_guard_judge_parser_error_is_diagnostic_not_finding(tmp_path):
    class MalformedClient:
        def complete(self, messages, *, max_tokens=None):
            return "not json"

    report = run_semantic_guard(
        case_id="breakdown_dependency_gap",
        module="breakdown",
        agent_output={"done_criteria": ["支持移动端和桌面端使用体验"]},
        workspace_state={"members": [], "project": {"tasks": []}},
        mode=SemanticGuardMode.auto,
        judge_client=MalformedClient(),
        cache_dir=tmp_path,
        use_cache=False,
        judge_model="deepseek-v4-flash",
    )

    assert report.called is True
    assert "judge_json_parse_error" in report.error_message
    assert report.findings == []
    assert report.hard_failures == []
    assert report.failure_categories == []
    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].kind.value == "judge_json_parse_error"


def test_semantic_guard_downgrades_judge_entity_fail_when_resolver_finds_id(tmp_path):
    class ContradictingClient:
        def complete(self, messages, *, max_tokens=None):
            return """
            {
              "findings": [
                {
                  "kind": "entity",
                  "span": "task-3",
                  "path": "agent_output.risks[0].task_id",
                  "decision": "FAIL",
                  "confidence": 0.95,
                  "evidence": "task-3 is not in the workspace.",
                  "failure_category": "hallucinated_entity",
                  "severity": "hard",
                  "source": "id_pattern"
                }
              ],
              "overall_decision": "FAIL",
              "confidence": 0.95
            }
            """

    report = run_semantic_guard(
        case_id="risk_checkin_blocker",
        module="risk",
        agent_output={
            "reason": "建议由张三协助处理 task-3",
            "risks": [{"task_id": "task-3", "evidence": ["task-3 被阻塞"]}],
        },
        workspace_state={"members": [], "project": {"tasks": [{"id": "task-3"}]}},
        mode=SemanticGuardMode.auto,
        judge_client=ContradictingClient(),
        cache_dir=tmp_path,
        use_cache=False,
        judge_model="deepseek-v4-flash",
    )

    assert report.called is True
    assert report.hard_failures == []
    assert report.failure_categories == []
    assert report.findings == []
    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].kind.value == "judge_state_mismatch"
    assert "workspace_state.project.tasks[0].id" in report.diagnostics[0].message


def test_semantic_guard_deterministic_fail_does_not_need_judge(tmp_path):
    class CountingClient:
        calls = 0

        def complete(self, messages, *, max_tokens=None):
            self.calls += 1
            return '{"findings": []}'

    client = CountingClient()
    report = run_semantic_guard(
        case_id="plan_scope_control",
        module="planning",
        agent_output={"deliverable": "实现教务系统课表对接"},
        workspace_state={"members": [], "project": {"tasks": []}},
        mode=SemanticGuardMode.auto,
        judge_client=client,
        cache_dir=tmp_path,
        use_cache=False,
        judge_model="deepseek-v4-flash",
    )

    assert report.called is False
    assert client.calls == 0
    assert "semantic_scope_failure" in report.hard_failures
    assert "scope_creep" in report.failure_categories
