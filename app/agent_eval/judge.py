"""LLM Judge for Agent Evaluation Benchmark.

The judge receives case metadata, expected/forbidden behavior, agent output,
and deterministic validator results, and returns structured scores.

Contains a deterministic ``StubJudge`` for mock-mode testing and a
``LLMJudge`` that uses an existing LLM client for real evaluation.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from app.agent_eval.schemas import EvalCase, JudgeResult, ValidatorResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Judge Protocol
# ---------------------------------------------------------------------------

class AgentJudge(Protocol):
    """Interface for all judge implementations."""

    def evaluate(
        self,
        case: EvalCase,
        agent_output: dict[str, Any] | None,
        *,
        validator_result: ValidatorResult | None = None,
        agent_status: str = "",
        raw_agent_output: str | None = None,
    ) -> JudgeResult:
        """Evaluate agent output against the case definition.

        Returns a ``JudgeResult``.  If the judge itself fails, the result
        must have ``passed=False`` and include ``"judge_failure"`` in
        ``failure_categories``.
        """


# ---------------------------------------------------------------------------
# Stub judge (deterministic, for tests and mock mode)
# ---------------------------------------------------------------------------

class StubJudge:
    """Deterministic stub that returns perfect or baseline scores.

    In mock mode the runner can configure ``baseline_score`` and
    ``baseline_dimensions`` to simulate different quality levels.
    """

    def __init__(
        self,
        *,
        baseline_score: float = 0.85,
        baseline_dimensions: dict[str, float] | None = None,
    ):
        self._baseline_score = baseline_score
        self._baseline_dimensions = baseline_dimensions or {}

    def evaluate(
        self,
        case: EvalCase,
        agent_output: dict[str, Any] | None,
        *,
        validator_result: ValidatorResult | None = None,
        agent_status: str = "",
        raw_agent_output: str | None = None,
    ) -> JudgeResult:
        """Return a deterministic judge result.

        Scores are downgraded if the agent fell back or failed.
        """
        score = self._baseline_score
        if agent_status == "failed":
            score = 0.0
        elif agent_status == "fallback" and not _case_expects_fallback(case):
            score = min(score, 0.6)

        dimensions = dict(self._baseline_dimensions)
        if not dimensions:
            # Default: use rubric weights as a baseline
            active = case.rubric_weights.active_dimensions()
            dimensions = {k: score for k in active}

        # If validator has hard failures, cap score
        if validator_result and not validator_result.passed:
            score = min(score, 0.3)

        passed = score >= case.minimum_score

        issues: list[str] = []
        if validator_result and validator_result.hard_failures:
            issues.append(f"Hard failures: {', '.join(validator_result.hard_failures)}")
        if agent_status == "fallback":
            issues.append("Agent used fallback output")
        elif agent_status == "failed":
            issues.append("Agent failed to produce output")

        return JudgeResult(
            overall_score=score,
            passed=passed,
            dimension_scores=dimensions,
            failure_categories=[],
            strengths=["Stub judge: deterministic evaluation"],
            issues=issues,
            evidence=["Stub judge: no evidence reference"],
        )


def _case_expects_fallback(case: EvalCase) -> bool:
    """Return whether fallback itself is the behavior under evaluation."""
    fallback_rules = {"empty_fallback", "unlabeled_fallback"}
    return (
        case.module == "reliability"
        and bool(fallback_rules.intersection(set(case.hard_fail_rules)))
    )


# ---------------------------------------------------------------------------
# Real LLM Judge
# ---------------------------------------------------------------------------

class LLMJudge:
    """LLM-based judge using an existing ``LLMClient``.

    The judge receives a prompt with the case definition and agent output,
    and must return strict JSON matching the ``JudgeResult`` schema.

    If the judge returns bad JSON or fails, the case is marked
    ``judge_failed`` rather than passing silently.
    """

    def __init__(
        self,
        llm_client: Any,
        *,
        model: str = "",
        temperature: float = 0.0,
        max_attempts: int = 2,
    ):
        self._llm_client = llm_client
        self._model = model
        self._temperature = temperature
        self._max_attempts = max(1, max_attempts)

    def evaluate(
        self,
        case: EvalCase,
        agent_output: dict[str, Any] | None,
        *,
        validator_result: ValidatorResult | None = None,
        agent_status: str = "",
        raw_agent_output: str | None = None,
    ) -> JudgeResult:
        """Run LLM judge evaluation.

        Returns a JudgeResult; if the LLM call or parsing fails, returns
        a failed result with ``judge_failure`` category.
        """
        prompt = self._build_prompt(case, agent_output, validator_result, agent_status)

        last_exc: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                raw = self._llm_client.complete(
                    [{"role": "user", "content": prompt}],
                    max_tokens=2000,
                )
                return self._parse_response(raw)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "LLM judge call failed on attempt %s/%s: %s",
                    attempt,
                    self._max_attempts,
                    exc,
                )

        return JudgeResult(
            overall_score=0.0,
            passed=False,
            failure_categories=["judge_failure"],
            issues=[f"LLM judge call failed after {self._max_attempts} attempts: {last_exc}"],
        )

    def _build_prompt(
        self,
        case: EvalCase,
        agent_output: dict[str, Any] | None,
        validator_result: ValidatorResult | None,
        agent_status: str,
    ) -> str:
        """Build the judge evaluation prompt."""
        return f"""你是一个 Agent 输出质量评估员。请根据以下 case 定义和 Agent 输出来评分。

## Case: {case.title}
- 模块: {case.module}
- 入口: {case.entrypoint}

### 期望行为
{self._format_list(case.expected_behavior)}

### 禁止行为
{self._format_list(case.forbidden_behavior)}

### Agent 状态
{agent_status or "unknown"}

### Agent 输出
```json
{json.dumps(agent_output, ensure_ascii=False, indent=2) if agent_output else "N/A"}
```

### 确定性校验结果
{json.dumps(validator_result.model_dump() if validator_result else {}, ensure_ascii=False, indent=2)}

### 评分约束
- **不得判断实体 ID 是否存在**。实体 ID 是否存在（task-N, user-N, stage-N, prop-N）由确定性解析器决定。
- 如果 Agent 引用了 task-3 等 ID，不要据此判 fail；这由确定性 validator 覆盖。
- 你有九成把握才输出 FAIL，否则用得分反映不确定性。
- 只有实体的语义合理性（如"让小林负责后端"是否合理）才由你判断。

请输出严格的 JSON 格式评分，包含以下字段：
- overall_score: 0-1 浮点数
- passed: bool（overall_score >= {case.minimum_score} 为 true）
- dimension_scores: dict[str, float] — 为以下维度评分：{', '.join(case.rubric_weights.active_dimensions().keys())}
- failure_categories: list[str] — 如果未通过，列出失败分类
- strengths: list[str] — 输出优点
- issues: list[str] — 输出问题
- evidence: list[str] — 支持评分的具体证据

只返回 JSON，不要有其他文字。"""

    def _parse_response(self, raw: str) -> JudgeResult:
        """Parse judge JSON response, handling failures gracefully."""
        # Try to extract JSON from the response
        cleaned = raw.strip()
        # Remove markdown code fences if present
        if cleaned.startswith("```"):
            # Find the first { or [
            start = cleaned.find("{")
            if start >= 0:
                cleaned = cleaned[start:]
            # Remove trailing backticks
            end = cleaned.rfind("}")
            if end >= 0:
                cleaned = cleaned[: end + 1]

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Bad JSON from judge: %s", raw[:200])
            return JudgeResult(
                overall_score=0.0,
                passed=False,
                failure_categories=["judge_failure"],
                issues=["Judge returned invalid JSON"],
                evidence=["Raw judge output could not be parsed"],
            )

        try:
            return JudgeResult(**data)
        except Exception as exc:
            logger.warning("Invalid judge result structure: %s", exc)
            return JudgeResult(
                overall_score=0.0,
                passed=False,
                failure_categories=["judge_failure"],
                issues=[f"Judge result validation failed: {exc}"],
            )

    @staticmethod
    def _format_list(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- (none)"
