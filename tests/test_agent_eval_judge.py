"""Tests for agent_eval judge module."""
from __future__ import annotations

from typing import Any

from app.agent_eval.judge import LLMJudge, StubJudge
from app.agent_eval.schemas import EvalCase, JudgeResult, RubricWeights, ValidatorResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_case(**overrides: Any) -> EvalCase:
    kwargs = dict(
        id="judge_test",
        title="Judge Test",
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
        forbidden_behavior=["bad"],
        rubric_weights=RubricWeights(context_grounding=0.5, mvp_boundary=0.3, actionability=0.2),
        minimum_score=0.8,
        hard_fail_rules=[],
    )
    kwargs.update(overrides)
    return EvalCase(**kwargs)


def _make_stub_judge(**kw: Any) -> StubJudge:
    return StubJudge(**kw)


# ---------------------------------------------------------------------------
# StubJudge tests
# ---------------------------------------------------------------------------


class TestStubJudge:
    def test_default_score(self):
        judge = _make_stub_judge()
        case = _make_case()
        result = judge.evaluate(case, {"reason": "test"})
        assert isinstance(result, JudgeResult)
        assert result.overall_score == 0.85
        assert result.passed

    def test_failed_agent_downgrades(self):
        judge = _make_stub_judge()
        case = _make_case()
        result = judge.evaluate(case, None, agent_status="failed")
        assert result.overall_score == 0.0
        assert not result.passed

    def test_fallback_agent_caps_score(self):
        judge = _make_stub_judge()
        case = _make_case()
        result = judge.evaluate(case, {"reason": "fallback"}, agent_status="fallback")
        assert result.overall_score <= 0.6

    def test_reliability_fallback_case_can_pass_when_fallback_is_expected(self):
        judge = _make_stub_judge()
        case = _make_case(
            id="fallback_bad_json",
            module="reliability",
            hard_fail_rules=["empty_fallback", "unlabeled_fallback"],
        )
        result = judge.evaluate(case, {"reason": "保守 fallback 建议"}, agent_status="fallback")
        assert result.overall_score == 0.85
        assert result.passed

    def test_hard_failures_cap_score(self):
        judge = _make_stub_judge()
        case = _make_case()
        v_result = ValidatorResult()
        v_result.add_finding("invalid_schema", "hard", False, "Bad schema")
        result = judge.evaluate(case, {"reason": "test"}, validator_result=v_result)
        assert result.overall_score <= 0.3
        assert not result.passed

    def test_custom_baseline(self):
        judge = _make_stub_judge(baseline_score=0.9)
        case = _make_case()
        result = judge.evaluate(case, {"reason": "test"})
        assert result.overall_score == 0.9

    def test_custom_dimensions(self):
        judge = _make_stub_judge(baseline_dimensions={"context_grounding": 0.9, "mvp_boundary": 0.8})
        case = _make_case()
        result = judge.evaluate(case, {"reason": "test"})
        assert result.dimension_scores.get("context_grounding") == 0.9
        assert result.dimension_scores.get("mvp_boundary") == 0.8

    def test_below_minimum_score_fails(self):
        judge = _make_stub_judge(baseline_score=0.5)
        case = _make_case(minimum_score=0.8)
        result = judge.evaluate(case, {"reason": "test"})
        assert not result.passed


# ---------------------------------------------------------------------------
# Mock LLM client for LLMJudge tests
# ---------------------------------------------------------------------------

class _MockLLMClient:
    """A mock LLM client that returns pre-configured responses."""

    def __init__(
        self,
        responses: list[str] | None = None,
        fail: bool = False,
        failures_before_success: int = 0,
    ):
        self.responses = responses or []
        self.calls = 0
        self._fail = fail
        self._failures_before_success = failures_before_success

    def complete(self, messages: list[dict], **kw: Any) -> str:
        self.calls += 1
        if self._fail or self.calls <= self._failures_before_success:
            raise RuntimeError("LLM call failed")
        idx = min(self.calls - 1, len(self.responses) - 1)
        return self.responses[idx] if self.responses else "{}"


GOOD_JUDGE_RESPONSE = """{
    "overall_score": 0.84,
    "passed": true,
    "dimension_scores": {
        "context_grounding": 0.9,
        "mvp_boundary": 1.0,
        "actionability": 0.75
    },
    "failure_categories": [],
    "strengths": ["明确列出未知项和待决策点"],
    "issues": ["下一步行动可以更具体到负责人或时间"],
    "evidence": ["Output mentions current_date 2026-06-05 and uses the project deadline"]
}"""

BAD_JSON_RESPONSE = "I think the score should be high."
MARKDOWN_FENCED_RESPONSE = """```json
{
    "overall_score": 0.9,
    "passed": true,
    "dimension_scores": {
        "context_grounding": 0.9
    },
    "failure_categories": [],
    "strengths": ["Good"],
    "issues": [],
    "evidence": ["Clear output"]
}
```"""

INCOMPLETE_RESPONSE = """{
    "overall_score": 0.9
}"""


# ---------------------------------------------------------------------------
# LLMJudge tests
# ---------------------------------------------------------------------------


class TestLLMJudge:
    def test_good_response(self):
        client = _MockLLMClient(responses=[GOOD_JUDGE_RESPONSE])
        judge = LLMJudge(client)
        case = _make_case()
        result = judge.evaluate(case, {"reason": "test"})
        assert result.overall_score == 0.84
        assert result.passed
        assert result.dimension_scores["context_grounding"] == 0.9

    def test_bad_json_returns_judge_failed(self):
        """Bad JSON from judge should result in judge_failure, not a pass."""
        client = _MockLLMClient(responses=[BAD_JSON_RESPONSE])
        judge = LLMJudge(client)
        case = _make_case()
        result = judge.evaluate(case, {"reason": "test"})
        assert not result.passed
        assert "judge_failure" in result.failure_categories
        assert result.overall_score == 0.0

    def test_markdown_fenced_json(self):
        """Judge response within markdown code fences should be parsed correctly."""
        client = _MockLLMClient(responses=[MARKDOWN_FENCED_RESPONSE])
        judge = LLMJudge(client)
        case = _make_case()
        result = judge.evaluate(case, {"reason": "test"})
        assert result.overall_score == 0.9
        assert result.passed

    def test_llm_call_failure(self):
        """LLM failure should result in judge_failed."""
        client = _MockLLMClient(fail=True)
        judge = LLMJudge(client)
        case = _make_case()
        result = judge.evaluate(case, {"reason": "test"})
        assert not result.passed
        assert "judge_failure" in result.failure_categories
        assert "LLM judge call failed" in (result.issues or [""])[0]

    def test_transient_llm_call_failure_retries_then_succeeds(self):
        """Transient judge transport failures should not become agent quality failures."""
        client = _MockLLMClient(
            responses=[GOOD_JUDGE_RESPONSE],
            failures_before_success=1,
        )
        judge = LLMJudge(client)
        case = _make_case()

        result = judge.evaluate(case, {"reason": "test"})

        assert client.calls == 2
        assert result.passed
        assert result.overall_score == 0.84
        assert "judge_failure" not in result.failure_categories

    def test_incomplete_response_valid_defaults(self):
        """Incomplete JSON that still satisfies JudgeResult defaults should work."""
        client = _MockLLMClient(responses=[INCOMPLETE_RESPONSE])
        judge = LLMJudge(client)
        case = _make_case()
        result = judge.evaluate(case, {"reason": "test"})
        assert result.overall_score == 0.9
        # Defaults fill in the rest
        assert result.passed  # default True with score 0.9
        assert result.failure_categories == []

    def test_model_and_temperature_passed(self):
        client = _MockLLMClient(responses=[GOOD_JUDGE_RESPONSE])
        judge = LLMJudge(client, model="test-model", temperature=0.5)
        assert judge._model == "test-model"
        assert judge._temperature == 0.5
        case = _make_case()
        result = judge.evaluate(case, {"reason": "test"}, agent_status="success")
        # Judge should still function
        assert result.overall_score == 0.84
