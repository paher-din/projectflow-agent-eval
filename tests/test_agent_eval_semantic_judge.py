from pathlib import Path

from app.agent.llm_client import MockLLMClient
from app.agent_eval.schemas import SemanticCandidate, SemanticCandidateDecision
from app.agent_eval.semantic_judge import (
    SemanticJudgeRequest,
    build_semantic_judge_cache_key,
    run_semantic_judge,
)


def test_semantic_judge_parses_structured_response(tmp_path: Path):
    client = MockLLMClient([
        """
        {
          "findings": [
            {
              "kind": "entity",
              "span": "周内",
              "path": "agent_output.raw_text",
              "decision": "PASS",
              "confidence": 0.95,
              "evidence": "Time expression, not a person.",
              "failure_category": "hallucinated_entity",
              "source": "time_or_range_pattern",
              "severity": "soft",
              "risk": "low"
            }
          ],
          "overall_decision": "PASS",
          "confidence": 0.95
        }
        """
    ])
    request = SemanticJudgeRequest(
        case_id="negotiate_timeline_only",
        module="negotiate",
        known_members=["小林", "小张"],
        known_tasks=["课程搜索页面"],
        scope_contract={},
        candidates=[
            SemanticCandidate(
                kind="entity",
                span="周内",
                path="agent_output.raw_text",
                local_context="15 小时/周内完成",
                deterministic_decision=SemanticCandidateDecision.ambiguous,
            )
        ],
    )

    report = run_semantic_judge(
        request,
        client=client,
        cache_dir=tmp_path,
        use_cache=False,
        model="deepseek-v4-flash",
    )

    assert report.called is True
    assert report.cache_hit is False
    assert len(report.findings) == 1
    assert report.findings[0].span == "周内"
    assert report.findings[0].decision.value == "PASS"


def test_semantic_judge_malformed_json_becomes_error_report(tmp_path: Path):
    client = MockLLMClient(["not json"])
    request = SemanticJudgeRequest(
        case_id="case_1",
        module="planning",
        known_members=[],
        known_tasks=[],
        scope_contract={},
        candidates=[],
    )

    report = run_semantic_judge(
        request,
        client=client,
        cache_dir=tmp_path,
        use_cache=False,
        model="deepseek-v4-flash",
    )

    assert report.called is True
    assert "judge_json_parse_error" in report.error_message
    assert report.findings == []
    assert report.failure_categories == []
    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].kind.value == "judge_json_parse_error"


def test_semantic_judge_schema_invalid_response_becomes_diagnostic(tmp_path: Path):
    client = MockLLMClient(['{"findings": [{"kind": "scope", "decision": "MAYBE"}]}'])
    request = SemanticJudgeRequest(
        case_id="case_1",
        module="planning",
        known_members=[],
        known_tasks=[],
        scope_contract={},
        candidates=[
            SemanticCandidate(
                kind="scope",
                span="移动端",
                path="agent_output.done_criteria[0]",
                deterministic_decision=SemanticCandidateDecision.ambiguous,
            )
        ],
    )

    report = run_semantic_judge(
        request,
        client=client,
        cache_dir=tmp_path,
        use_cache=False,
        model="deepseek-v4-flash",
    )

    assert "judge_schema_error" in report.error_message
    assert report.findings == []
    assert report.failure_categories == []
    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].kind.value == "judge_schema_error"


def test_semantic_judge_normalizes_finding_aliases_and_scope_category(tmp_path: Path):
    client = MockLLMClient([
        """
        {
          "scope_findings": [
            {
              "span": "移动端",
              "path": "agent_output.stages[1].goal",
              "result": "VIOLATION",
              "confidence": 0.91,
              "reason": "The output commits to mobile app delivery.",
              "failure_category": "schema_failure",
              "severity": "hard",
              "source": "ambiguous_term"
            }
          ],
          "verdict": "FAILED",
          "confidence": 0.91
        }
        """
    ])
    request = SemanticJudgeRequest(
        case_id="plan_scope_control",
        module="planning",
        known_members=[],
        known_tasks=[],
        scope_contract={},
        candidates=[
            SemanticCandidate(
                kind="scope",
                span="移动端",
                path="agent_output.stages[1].goal",
                deterministic_decision=SemanticCandidateDecision.ambiguous,
            )
        ],
    )

    report = run_semantic_judge(
        request,
        client=client,
        cache_dir=tmp_path,
        use_cache=False,
        model="deepseek-v4-flash",
    )

    assert report.error_message == ""
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.decision.value == "FAIL"
    assert finding.evidence == "The output commits to mobile app delivery."
    assert finding.failure_category == "scope_creep"
    assert "schema_failure" not in report.failure_categories
    assert report.failure_categories == ["scope_creep"]
    assert any(d.kind.value == "judge_contract_violation" for d in report.diagnostics)


def test_semantic_judge_schema_error_decision_is_uncertain_not_hard_fail(tmp_path: Path):
    client = MockLLMClient([
        """
        {
          "findings": [
            {
              "kind": "scope",
              "span": "桌面端",
              "path": "agent_output.tasks[2].acceptance_criteria[3]",
              "decision": "SCHEMA_ERROR",
              "confidence": 0.95,
              "evidence": "Model confused scope contract with schema.",
              "failure_category": "schema_failure",
              "severity": "hard",
              "source": "ambiguous_term"
            }
          ],
          "overall_decision": "SCHEMA_ERROR",
          "confidence": 0.95
        }
        """
    ])
    request = SemanticJudgeRequest(
        case_id="breakdown_dependency_gap",
        module="breakdown",
        known_members=[],
        known_tasks=[],
        scope_contract={},
        candidates=[
            SemanticCandidate(
                kind="scope",
                span="桌面端",
                path="agent_output.tasks[2].acceptance_criteria[3]",
                deterministic_decision=SemanticCandidateDecision.ambiguous,
            )
        ],
    )

    report = run_semantic_judge(
        request,
        client=client,
        cache_dir=tmp_path,
        use_cache=False,
        model="deepseek-v4-flash",
    )

    assert report.error_message == ""
    assert report.hard_failures == []
    assert report.failure_categories == []
    assert report.findings[0].decision.value == "UNCERTAIN"
    assert report.findings[0].failure_category is None
    assert any(d.kind.value == "judge_contract_violation" for d in report.diagnostics)


def test_semantic_judge_cache_key_includes_model():
    request = SemanticJudgeRequest(
        case_id="case_1",
        module="planning",
        known_members=["小林"],
        known_tasks=["任务 A"],
        scope_contract={"allowed": ["Web MVP"]},
        candidates=[],
    )

    key_a = build_semantic_judge_cache_key(request, model="deepseek-v4-flash")
    key_b = build_semantic_judge_cache_key(request, model="other-lite-model")

    assert key_a != key_b


def test_semantic_judge_cache_key_includes_prompt_version():
    request = SemanticJudgeRequest(
        case_id="case_1",
        module="planning",
        known_members=[],
        known_tasks=[],
        scope_contract={},
        candidates=[],
    )

    key_a = build_semantic_judge_cache_key(request, model="deepseek-v4-flash", prompt_version="prompt-a")
    key_b = build_semantic_judge_cache_key(request, model="deepseek-v4-flash", prompt_version="prompt-b")

    assert key_a != key_b
