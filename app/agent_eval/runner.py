#!/usr/bin/env python
"""Agent Evaluation Benchmark Runner.

Usage (dev/CLI)::

    # Mock mode (no real LLM, default)
    python -m app.agent_eval.runner run --mode mock --fixtures app/agent_eval/fixtures --output-dir output/agent-eval

    # Real mode (uses existing backend LLM config)
    python -m app.agent_eval.runner run --mode real --fixtures app/agent_eval/fixtures --output-dir output/agent-eval

    # Compare two runs
    python -m app.agent_eval.runner compare output/agent-eval/run-abc output/agent-eval/run-xyz

    # List available fixtures
    python -m app.agent_eval.runner list-fixtures --fixtures app/agent_eval/fixtures
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from app.agent_eval.case_loader import load_fixtures, list_fixture_ids
from app.agent_eval.judge import LLMJudge, StubJudge
from app.agent_eval.report_writer import (
    build_suite_summary,
    compare_runs,
    write_case_report,
    write_markdown_summary,
    write_suite_summary,
)
from app.agent_eval.semantic_guard import run_semantic_guard
from app.agent_eval.semantic_judge import (
    SEMANTIC_JUDGE_PROMPT_VERSION,
    build_semantic_judge_client,
)
from app.agent_eval.schemas import (
    CaseReport,
    CaseStatus,
    FailureCategory,
    JudgeResult,
    RunConfig,
    SemanticGuardMode,
    SemanticGuardReport,
    SemanticJudgeDiagnostic,
    SemanticJudgeDiagnosticKind,
    SuiteSummary,
    ValidatorResult,
)
from app.core.config import settings as app_settings
from app.agent_eval.validators import run_all_validators
from app.agent_eval.entity_resolver import (
    build_workspace_entity_index,
    resolve_workspace_entity,
)
from app.agent_eval.assertion_engine import (
    build_default_assertions_for_case,
    compute_assertion_metrics,
    run_all_assertions as evaluate_assertions,
)

if TYPE_CHECKING:
    from app.agent.coordinator import CoordinatorAgent
    from app.agent.llm_client import LLMClient, build_agent_llm_client
    from app.agent.workflow import AgentRunResult
    from app.schemas.workspace_state import WorkspaceStateResponse

logger = logging.getLogger(__name__)

OUTPUT_BASE = Path("output") / "agent-eval"
DEFAULT_CACHE_DIR = OUTPUT_BASE / ".cache"
_AGENT_SOURCE_HASH: str | dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Agent invocation (mock)
# ---------------------------------------------------------------------------

def _mock_agent_output(entrypoint: str) -> dict[str, Any]:
    """Return a deterministic mock output for the given entrypoint.

    The mock output is a minimally-valid dict matching the expected
    schema for each agent module.
    """
    outputs: dict[str, dict[str, Any]] = {
        "clarify": {
            "reason": "当前日期 2026-06-05，项目信息不足，需要进一步澄清",
            "requires_confirmation": True,
            "problem": "学习规划缺乏系统性",
            "users": "在校大学生",
            "value": "提供个性化的学习规划建议",
            "deliverables": ["学习规划 Web 应用"],
            "boundaries": ["第一版只做单项目 Web MVP", "仅使用团队手动录入的信息"],
            "risks": ["用户数据隐私"],
            "suggested_questions": ["目标用户群体是什么"],
            "assumptions": ["用户有意愿填写学习习惯"],
            "unknowns": ["用户获取渠道"],
            "mvp_boundary": {
                "must_have": ["学习规划生成"],
                "defer": ["社交功能"],
                "out_of_scope": ["跨团队协作", "生产部署自动化"],
            },
            "decision_points": ["是否支持课程表导入"],
        },
        "plan": {
            "reason": "根据 deadline 和当前日期 2026-06-05 规划阶段",
            "requires_confirmation": True,
            "stages": [
                {
                    "name": "基础搭建",
                    "goal": "搭建项目基础设施",
                    "start_date": "2026-06-08",
                    "end_date": "2026-06-20",
                    "deliverable": "项目基础框架",
                    "done_criteria": ["框架搭建完成"],
                    "order_index": 0,
                    "reason": "先搭建基础框架",
                },
                {
                    "name": "核心功能",
                    "goal": "实现核心功能",
                    "start_date": "2026-06-21",
                    "end_date": "2026-07-10",
                    "deliverable": "核心功能可用",
                    "done_criteria": ["功能测试通过"],
                    "order_index": 1,
                    "reason": "核心功能为主",
                },
            ],
        },
        "breakdown": {
            "reason": "根据阶段目标拆解任务",
            "requires_confirmation": True,
            "tasks": [
                {
                    "id": "task-db",
                    "title": "数据库设计与建表",
                    "description": "设计核心数据表",
                    "priority": "P0",
                    "due_date": "2026-06-12",
                    "estimated_hours": 8,
                    "can_cut": False,
                    "acceptance_criteria": ["数据表设计文档完成"],
                    "dependency_ids": [],
                    "reason": "基础数据层必须先完成",
                },
                {
                    "id": "task-api",
                    "title": "后端 API 开发",
                    "description": "实现 REST API",
                    "priority": "P0",
                    "due_date": "2026-06-20",
                    "estimated_hours": 20,
                    "can_cut": False,
                    "acceptance_criteria": ["API 可调用"],
                    "dependency_ids": ["task-db"],
                    "reason": "核心功能的后端支持",
                },
                {
                    "id": "task-ui",
                    "title": "前端页面开发",
                    "description": "实现用户界面",
                    "priority": "P0",
                    "due_date": "2026-06-25",
                    "estimated_hours": 15,
                    "can_cut": False,
                    "acceptance_criteria": ["页面可交互"],
                    "dependency_ids": ["task-api"],
                    "reason": "用户交互入口",
                },
            ],
        },
        "recommend-assignments": {
            "reason": "根据成员技能和可用时间推荐分工",
            "requires_confirmation": True,
            "assignments": [
                {
                    "task_id": "task-1",
                    "recommended_owner_user_id": "user-1",
                    "reason": "小林具备该任务所需技能",
                    "skill_match": "backend",
                    "availability_match": "15 小时可覆盖本周后端任务",
                }
            ],
        },
        "negotiate": {
            "reason": "根据成员拒绝响应提出交换建议",
            "requires_confirmation": True,
            "from_user_id": "user-2",
            "desired_task_id": "task-1",
            "current_owner_user_id": "user-1",
            "message": "小张希望调整到后端任务，可让小林确认是否交换。",
            "options": ["小林接受交换", "小张继续原前端任务"],
        },
        "active-push": {
            "reason": "根据 check-in 状态生成行动卡",
            "action_cards": [
                {
                    "type": "personal_task",
                    "title": "推进课程搜索 API",
                    "content": "先把模糊搜索降级为 SQLite LIKE 查询，保证主流程可演示。",
                    "reason": "小林在 check-in 中报告模糊搜索方案卡住。",
                    "goal": "解除后端搜索接口 blocker",
                    "start_suggestion": "先实现课程名 LIKE 查询并写一个最小接口测试。",
                    "completion_standard": "搜索接口可以按课程名返回结果。",
                    "user_id": "user-1",
                    "task_id": "task-1",
                    "due_date": "2026-06-20",
                }
            ],
        },
        "analyze-risk": {
            "reason": "根据 check-in blocker 识别风险",
            "requires_confirmation": True,
            "risks": [
                {
                    "type": "deadline",
                    "severity": "high",
                    "title": "核心功能可能无法按期交付",
                    "description": "后端 API 的 blocker 会连带影响前端联调。",
                    "evidence": ["有成员在 check-in 中报告技术方案不确定"],
                    "recommendation": "简化技术方案",
                }
            ],
        },
        "replan": {
            "reason": "截止期临近需要调整计划",
            "requires_confirmation": True,
            "before": {"status": "当前计划"},
            "after": {
                "status": "调整后计划",
            },
            "impact": "核心功能可以按期交付，范围有所缩小",
            "task_changes": [],
        },
        "analyze-checkin": {
            "reason": "根据签到数据分析团队进度",
            "requires_confirmation": True,
            "summary": "本周签到完成率 60%，核心任务进度正常，但存在依赖阻塞需要关注。",
            "task_updates": [
                {
                    "task_id": "task-1",
                    "status": "in_progress",
                    "progress": 60,
                    "note": "核心任务进度正常",
                },
            ],
            "risks": [
                {
                    "type": "dependency",
                    "severity": "medium",
                    "description": "外部依赖未确定影响开发进度",
                    "affected_task_ids": ["task-1"],
                },
            ],
        },
    }

    return outputs.get(entrypoint, {"reason": "Mock output", "requires_confirmation": False})


def _get_entrypoint_from_case(case: Any) -> str:
    """Map case entrypoint to a mock output key."""
    ep = case.entrypoint
    mapping = {
        "clarify": "clarify",
        "plan": "plan",
        "breakdown": "breakdown",
        "recommend-assignments": "recommend-assignments",
        "negotiate": "negotiate",
        "active-push": "active-push",
        "analyze-risk": "analyze-risk",
        "replan": "replan",
        "analyze-checkin": "analyze-checkin",
    }
    return mapping.get(ep, ep)


def _run_real_agent_flow(case: Any, llm_client: "LLMClient", projectflow_root: str = "") -> "AgentRunResult":
    """Invoke the existing Agent flow without product-facing persistence."""
    from app.agent.coordinator import CoordinatorAgent
    from app.agent.workflow import AgentRunResult
    from app.schemas.workspace_state import WorkspaceStateResponse

    workspace_state = WorkspaceStateResponse(**case.workspace_state)
    coordinator = CoordinatorAgent(llm_client=llm_client, session=None)
    entrypoint = _get_entrypoint_from_case(case)

    if entrypoint == "clarify":
        return coordinator.generate_direction_card(workspace_state)
    if entrypoint == "plan":
        return coordinator.generate_stage_plan(workspace_state)
    if entrypoint == "breakdown":
        return coordinator.generate_task_breakdown(workspace_state)
    if entrypoint == "recommend-assignments":
        return coordinator.recommend_assignments(workspace_state)
    if entrypoint == "negotiate":
        return coordinator.negotiate_assignment(workspace_state)
    if entrypoint == "active-push":
        return coordinator.create_active_push(workspace_state)
    if entrypoint == "analyze-risk":
        return coordinator.analyze_risks(workspace_state)
    if entrypoint == "replan":
        return coordinator.replan(workspace_state)
    if entrypoint == "analyze-checkin":
        return coordinator.analyze_checkin(workspace_state)

    raise ValueError(f"Unsupported real-mode entrypoint: {entrypoint}")


# ---------------------------------------------------------------------------
# Core run logic
# ---------------------------------------------------------------------------

def run_case(
    case: Any,
    *,
    mode: str = "mock",
    llm_client: Any = None,
    model: str = "",
    judge_mode: str = "auto",
    cache_dir: str | Path | None = None,
    use_cache: bool = False,
    cache_context: dict[str, Any] | None = None,
    semantic_guard_mode: SemanticGuardMode | str = SemanticGuardMode.auto,
    semantic_judge_client: "LLMClient | None" = None,
    semantic_judge_model: str = "",
    semantic_judge_base_url: str = "",
    projectflow_root: str = "",
) -> CaseReport:
    """Execute a single benchmark case.

    In mock mode, returns a deterministic stub output.
    In real mode, invokes the existing Agent flow without product persistence.
    """
    agent_output: dict[str, Any] | None = None
    agent_status = "success"
    raw_agent_output: str | None = None
    attempts = 1
    used_fallback = False
    error_message = ""
    owns_llm_client = False
    cache_hit = False
    cache_key = ""
    start = time.monotonic()

    entrypoint = _get_entrypoint_from_case(case)
    selected_semantic_guard_mode = _normalize_semantic_guard_mode(semantic_guard_mode)
    selected_semantic_judge_model = _selected_semantic_judge_model(semantic_judge_model)
    selected_semantic_judge_base_url = _selected_semantic_judge_base_url(semantic_judge_base_url)

    if mode == "mock":
        # Deterministic mock agent
        agent_output = _mock_agent_output(entrypoint)
        # For fallback_bad_json case, simulate fallback behavior
        if case.id == "fallback_bad_json":
            agent_status = "fallback"
            used_fallback = True
            # But make the fallback valid (non-empty, Chinese, actionable)
            agent_output = {
                "reason": "由于 LLM 响应异常，使用保守方案",
                "requires_confirmation": True,
                "problem": "帮助学生学习规划",
                "users": "在校大学生",
                "value": "提供基础学习规划建议",
                "deliverables": ["基础学习规划页面"],
                "boundaries": [],
                "risks": [],
                "suggested_questions": ["你想要规划哪些科目？"],
                "assumptions": ["用户有明确学习目标"],
                "unknowns": ["具体学习内容"],
                "mvp_boundary": None,
                "decision_points": [],
            }
    else:
        try:
            selected_cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
            cache_key = _build_agent_cache_key(
                case,
                model=model,
                cache_context=cache_context,
                projectflow_root=projectflow_root,
            )
            cached = _read_agent_cache(selected_cache_dir, cache_key) if use_cache else None
            if cached is not None:
                cache_hit = True
                agent_output = cached.get("agent_output")
                agent_status = cached.get("agent_status", "success")
                attempts = int(cached.get("attempts", 1))
                used_fallback = bool(cached.get("used_fallback", False))
                raw_agent_output = cached.get("raw_agent_output")
            else:
                if llm_client is None:
                    from app.agent.llm_client import build_agent_llm_client

                    llm_client = build_agent_llm_client()
                    owns_llm_client = True
                real_result = _run_real_agent_flow(case, llm_client, projectflow_root=projectflow_root)
                agent_output = real_result.output.model_dump(mode="json")
                agent_status = real_result.status.value
                attempts = real_result.attempts
                used_fallback = real_result.used_fallback
                raw_agent_output = real_result.raw_output
                if use_cache and agent_output is not None and agent_status != "failed":
                    _write_agent_cache(
                        selected_cache_dir,
                        cache_key,
                        {
                            "agent_output": agent_output,
                            "agent_status": agent_status,
                            "attempts": attempts,
                            "used_fallback": used_fallback,
                            "raw_agent_output": raw_agent_output,
                        },
                    )
        except Exception as exc:
            agent_status = "failed"
            error_message = f"Real mode agent invocation failed: {exc}"

    # Run deterministic validators
    validator_result = run_all_validators(
        case,
        agent_output,
        agent_status=agent_status,
        raw_agent_output=raw_agent_output,
        workspace_state=case.workspace_state,
    )

    # Run v2 assertions
    case_assertions = case.assertions or build_default_assertions_for_case(
        case_id=case.id,
        module=case.module,
        entrypoint=entrypoint,
    )
    assertion_results_raw = evaluate_assertions(
        case_assertions,
        agent_output,
        agent_status=agent_status,
        workspace_state=case.workspace_state,
        raw_agent_output=raw_agent_output,
        entrypoint=entrypoint,
    )
    assertion_metrics = compute_assertion_metrics(assertion_results_raw)

    # Run judge after deterministic checks so real mode can skip redundant LLM calls.
    judge_result = _run_judge(
        case,
        agent_output,
        validator_result=validator_result,
        assertion_results=assertion_results_raw,
        assertion_metrics=assertion_metrics,
        case_assertions=case_assertions,
        agent_status=agent_status,
        raw_agent_output=raw_agent_output,
        mode=mode,
        llm_client=llm_client,
        judge_mode=judge_mode,
    )

    # ── Sanitize judge result: downgrade fabricated_entity / hallucinated_entity ──
    # ── failure categories when the deterministic resolver confirms all IDs.     ──
    if judge_result is not None and agent_output is not None:
        _sanitize_judge_entity_failures(
            judge_result,
            case.workspace_state,
            agent_output,
            minimum_score=case.minimum_score,
        )

    semantic_guard_report = _run_semantic_guard_for_case(
        case,
        agent_output,
        mode=mode,
        semantic_guard_mode=selected_semantic_guard_mode,
        semantic_judge_client=semantic_judge_client,
        semantic_judge_model=selected_semantic_judge_model,
        semantic_judge_base_url=selected_semantic_judge_base_url,
        cache_dir=Path(cache_dir or DEFAULT_CACHE_DIR),
        use_cache=use_cache and mode == "real",
    )

    # Build case report
    score = judge_result.overall_score if judge_result else 0.0

    # Override: hard failures always fail
    has_hard_failures = not validator_result.passed
    has_semantic_hard_failures = bool(semantic_guard_report.hard_failures)
    hard_failures = list(validator_result.hard_failures)
    for hard_failure in semantic_guard_report.hard_failures:
        if hard_failure not in hard_failures:
            hard_failures.append(hard_failure)

    failure_categories: list[str] = []
    for category in list(judge_result.failure_categories) if judge_result else []:
        _append_unique(failure_categories, category)
    for category in _failure_categories_for_validator_result(validator_result):
        _append_unique(failure_categories, category)
    for category in semantic_guard_report.failure_categories:
        _append_unique(failure_categories, category)
    if (
        selected_semantic_guard_mode == SemanticGuardMode.required
        and semantic_guard_report.error_message
    ):
        _append_unique(failure_categories, FailureCategory.judge_failure.value)

    if (
        selected_semantic_guard_mode == SemanticGuardMode.required
        and semantic_guard_report.error_message
        and not has_hard_failures
        and not has_semantic_hard_failures
    ):
        status = CaseStatus.judge_failed
        if not error_message:
            error_message = semantic_guard_report.error_message
    elif judge_result and "judge_failure" in judge_result.failure_categories and not has_hard_failures:
        status = CaseStatus.judge_failed
    elif has_hard_failures or has_semantic_hard_failures or (judge_result and not judge_result.passed):
        status = CaseStatus.failed
    else:
        status = CaseStatus.passed

    # Override: v1 hard failures force failed status regardless of judge
    if not validator_result.passed or has_semantic_hard_failures:
        status = CaseStatus.failed
        score = min(score, 0.0)
        if "judge_failure" in failure_categories:
            failure_categories.remove("judge_failure")

    # Override: v2 assertion hard failures also force fail
    if assertion_metrics.get("hard_fail_count", 0) > 0:
        status = CaseStatus.failed
        for cat in assertion_metrics.get("failure_categories", []):
            if cat and cat not in failure_categories:
                failure_categories.append(cat)

    assertion_score = assertion_metrics.get("weighted_score", score)
    if assertion_results_raw and assertion_score < case.minimum_score:
        status = CaseStatus.failed
        for cat in assertion_metrics.get("failure_categories", []):
            if cat and cat not in failure_categories:
                failure_categories.append(cat)
        if not assertion_metrics.get("failure_categories") and "weak_actionability" not in failure_categories:
            failure_categories.append("weak_actionability")

    report = CaseReport(
        run_id="",
        case_id=case.id,
        module=case.module,
        model=model,
        status=status,
        hard_failures=hard_failures,
        overall_score=score,
        dimension_scores=judge_result.dimension_scores if judge_result else {},
        failure_categories=failure_categories,
        agent_status=agent_status,
        used_fallback=used_fallback,
        attempts=attempts,
        output_path="",
        agent_output=agent_output,
        raw_agent_output=raw_agent_output,
        validator_result=validator_result,
        judge_result=judge_result,
        error_message=error_message,
        duration_seconds=round(time.monotonic() - start, 4),
        cache_hit=cache_hit,
        cache_key=cache_key if use_cache else "",
        assertion_results=assertion_results_raw,
        hard_fail_count=assertion_metrics.get("hard_fail_count", 0),
        weighted_score=assertion_score,
        case_pass=status == CaseStatus.passed,
        semantic_guard=semantic_guard_report,
    )
    if owns_llm_client and hasattr(llm_client, "close"):
        llm_client.close()
    return report


def _build_agent_cache_key(
    case: Any,
    *,
    model: str,
    cache_context: dict[str, Any] | None = None,
    projectflow_root: str = "",
) -> str:
    context = dict(cache_context or {})
    source_hash = context.pop("source_hash", None) or _agent_source_hash(projectflow_root)
    payload = {
        "version": 1,
        "kind": "projectflow-agent-output",
        "case": case.model_dump(mode="json") if hasattr(case, "model_dump") else case,
        "model": model or os.getenv("LLM_MODEL", ""),
        "provider": os.getenv("LLM_PROVIDER", ""),
        "base_url_host": _host_from_base_url(os.getenv("LLM_BASE_URL", "")),
        "source_hash": source_hash,
        "projectflow_root": projectflow_root,
        "context": context,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _agent_source_hash(projectflow_root: str = "") -> str:
    global _AGENT_SOURCE_HASH
    cache_key = projectflow_root or "__repo__"
    if isinstance(_AGENT_SOURCE_HASH, dict):
        cached = _AGENT_SOURCE_HASH.get(cache_key)
        if cached is not None:
            return cached
    elif _AGENT_SOURCE_HASH is not None and not projectflow_root:
        return _AGENT_SOURCE_HASH

    if projectflow_root:
        agent_root = Path(projectflow_root) / "app" / "agent"
    else:
        backend_root = Path(__file__).resolve().parents[2]
        agent_root = backend_root / "app" / "agent"

    digest = hashlib.sha256()
    for path in sorted(agent_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(str(path.relative_to(agent_root.parent.parent)).encode("utf-8"))
        digest.update(path.read_bytes())

    result = digest.hexdigest()

    if projectflow_root:
        if not isinstance(_AGENT_SOURCE_HASH, dict):
            _AGENT_SOURCE_HASH = {}
        _AGENT_SOURCE_HASH[cache_key] = result
    else:
        _AGENT_SOURCE_HASH = result

    return result


def _read_agent_cache(cache_dir: Path, cache_key: str) -> dict[str, Any] | None:
    path = cache_dir / f"{cache_key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Ignoring corrupt agent eval cache entry: %s", path)
        return None


def _write_agent_cache(cache_dir: Path, cache_key: str, payload: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{cache_key}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_judge(
    case: Any,
    agent_output: dict[str, Any] | None,
    *,
    validator_result: ValidatorResult | None = None,
    assertion_results: list[Any] | None = None,
    assertion_metrics: dict[str, Any] | None = None,
    case_assertions: list[Any] | None = None,
    agent_status: str = "",
    raw_agent_output: str | None = None,
    mode: str = "mock",
    llm_client: Any = None,
    judge_mode: str = "auto",
) -> JudgeResult:
    """Run the judge for a case.

    Optimization: when deterministic validators already found hard failures,
    skip the LLM judge call and return a stub result immediately.  The case
    is already going to fail regardless of what the judge says.
    """
    normalized_judge_mode = judge_mode.lower()
    if normalized_judge_mode not in {"auto", "llm", "stub"}:
        raise ValueError("judge_mode must be one of: auto, llm, stub")

    # ── skip LLM judge when validators already hard-fail ──────────────
    if (
        mode == "real"
        and validator_result is not None
        and not validator_result.passed
    ):
        logger.info(
            "Skipping LLM judge for %s: validator hard failures → %s",
            case.id,
            validator_result.hard_failures,
        )
        score = 0.0
        return JudgeResult(
            overall_score=score,
            passed=False,
            dimension_scores={
                k: score for k in case.rubric_weights.active_dimensions()
            },
            failure_categories=_failure_categories_for_validator_result(validator_result),
            strengths=[],
            issues=[
                f"Validator hard failure: {hf}"
                for hf in validator_result.hard_failures
            ],
            evidence=["Judge skipped: deterministic hard failure detected."],
        )

    if mode == "real" and normalized_judge_mode == "stub":
        return StubJudge(
            baseline_score=_assertion_score_or_default(assertion_metrics),
            baseline_dimensions=case.rubric_weights.active_dimensions(),
        ).evaluate(
            case,
            agent_output,
            validator_result=validator_result,
            agent_status=agent_status,
            raw_agent_output=raw_agent_output,
        )

    if (
        mode == "real"
        and normalized_judge_mode == "auto"
        and _can_use_deterministic_judge(case_assertions, assertion_results)
    ):
        score = _assertion_score_or_default(assertion_metrics)
        failure_categories = list(assertion_metrics.get("failure_categories", [])) if assertion_metrics else []
        failed_ids = list(assertion_metrics.get("failed_assertion_ids", [])) if assertion_metrics else []
        return JudgeResult(
            overall_score=score,
            passed=score >= case.minimum_score,
            dimension_scores={
                k: score for k in case.rubric_weights.active_dimensions()
            },
            failure_categories=failure_categories,
            strengths=["Deterministic assertions covered this case"],
            issues=[
                f"Assertion failed: {assertion_id}"
                for assertion_id in failed_ids
            ],
            evidence=["Judge skipped: deterministic assertions covered this case."],
        )

    # ── normal judge path ─────────────────────────────────────────────
    if mode == "mock":
        judge = StubJudge(
            baseline_score=0.85,
            baseline_dimensions=case.rubric_weights.active_dimensions(),
        )
    else:
        if llm_client is None:
            # Fall back to stub if no real LLM client available
            judge = StubJudge(baseline_score=0.7)
        else:
            judge = LLMJudge(llm_client)

    return judge.evaluate(
        case,
        agent_output,
        validator_result=validator_result,
        agent_status=agent_status,
        raw_agent_output=raw_agent_output,
    )


def _assertion_score_or_default(assertion_metrics: dict[str, Any] | None) -> float:
    if not assertion_metrics:
        return 0.85
    return float(assertion_metrics.get("weighted_score", 0.85))


def _can_use_deterministic_judge(
    assertions: list[Any] | None, assertion_results: list[Any] | None
) -> bool:
    if not assertions or not assertion_results:
        return False
    semantic_evaluators = {"llm_semantic"}
    for assertion in assertions:
        evaluator = getattr(assertion.evaluator, "value", assertion.evaluator)
        if evaluator in semantic_evaluators:
            return False
    return True


def _sanitize_judge_entity_failures(
    judge_result: JudgeResult,
    workspace_state: dict[str, Any],
    agent_output: dict[str, Any],
    *,
    minimum_score: float,
) -> bool:
    """Remove ``fabricated_entity`` / ``hallucinated_entity`` from ``JudgeResult`` when the
    deterministic entity resolver confirms that all ID-like references in the agent output
    are known entities.

    When all referenced entities exist in the workspace state (or are output-defined IDs
    that the resolver accepts), the fabrication claim is a judge hallucination — not a
    genuine agent quality issue.  It is downgraded to a ``judge_state_mismatch`` diagnostic.

    Returns ``True`` if the result was modified.
    """
    entity_cats = {"fabricated_entity", "hallucinated_entity"}
    has_entity_failure = any(cat in judge_result.failure_categories for cat in entity_cats)
    if not has_entity_failure:
        return False

    import re
    id_re = re.compile(r"\b(?:user|task|stage|prop)-[A-Za-z0-9_-]+\b")
    index = build_workspace_entity_index(workspace_state)

    # Collect output-defined IDs (newly generated tasks/proposals)
    output_ids = _collect_output_defined_entity_ids(agent_output)

    # Collect all entity ID references from agent_output
    agent_text = str(agent_output)
    referenced_ids = set(id_re.findall(agent_text))

    # Subtract known (resolved + generated) IDs
    known_ids = set(index.keys()) | output_ids
    genuinely_fabricated = referenced_ids - known_ids

    if genuinely_fabricated:
        # The judge correctly identified genuinely missing entities — do not override
        return False

    if not referenced_ids:
        # No structured entity IDs in output — can't verify fabrication claim
        return False

    # All ID references are known — downgrade the fabrication category
    remaining = [c for c in judge_result.failure_categories if c not in entity_cats]
    judge_result.failure_categories = remaining

    # Build diagnostic with resolved paths
    path_parts: list[str] = []
    for eid in sorted(referenced_ids & set(index.keys())):
        path_parts.append(f"{eid} at {index[eid].state_path}")

    if not hasattr(judge_result, "diagnostics") or judge_result.diagnostics is None:
        judge_result.diagnostics = []
    judge_result.diagnostics.append(SemanticJudgeDiagnostic(
        kind=SemanticJudgeDiagnosticKind.judge_state_mismatch,
        message=(
            "LLM judge claimed entity fabrication but all ID references "
            f"verified by deterministic resolver: {'; '.join(path_parts)}"
        ),
        diagnostic_only=True,
        case_impact="none",
    ))

    if not judge_result.failure_categories:
        judge_result.passed = True
        if judge_result.overall_score < minimum_score:
            judge_result.overall_score = minimum_score

    return True


def _collect_output_defined_entity_ids(agent_output: dict[str, Any]) -> set[str]:
    """Collect entity IDs defined by the agent output itself (newly generated)."""
    import re
    id_re = re.compile(r"\b(?:user|task|stage|prop)-[A-Za-z0-9_-]+\b")
    defined: set[str] = set()
    for path, value in _walk_agent_output(agent_output):
        if not isinstance(value, str):
            continue
        key_part = _path_key(path)
        if key_part not in {"id", "proposal_id"}:
            continue
        if id_re.fullmatch(value.strip()):
            defined.add(value.strip())
    return defined


def _path_key(path: str) -> str:
    import re
    normalized = re.sub(r"\[\d+\]", "", path)
    return normalized.rsplit(".", 1)[-1]


def _walk_agent_output(value: Any, path: str = "agent_output") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        items: list[tuple[str, Any]] = []
        for key, child in value.items():
            items.extend(_walk_agent_output(child, f"{path}.{key}"))
        return items
    if isinstance(value, list):
        items = []
        for index, child in enumerate(value):
            items.extend(_walk_agent_output(child, f"{path}[{index}]"))
        return items
    return [(path, value)]


_VALIDATOR_FAILURE_CATEGORY_BY_RULE = {
    "invalid_schema": FailureCategory.schema_failure.value,
    "missing_status": FailureCategory.repair_failure.value,
    "fabricated_workspace_entity": FailureCategory.hallucinated_entity.value,
    "violates_mvp_boundary": FailureCategory.scope_creep.value,
    "unsafe_persistence": FailureCategory.persistence_boundary_violation.value,
    "negotiate_created_generic_proposal": FailureCategory.wrong_module_behavior.value,
    "missing_reason": FailureCategory.weak_explainability.value,
    "empty_fallback": FailureCategory.fallback_quality_failure.value,
    "date_miscalculation": FailureCategory.date_time_error.value,
    "unlabeled_fallback": FailureCategory.fallback_quality_failure.value,
}


def _failure_categories_for_validator_result(result: ValidatorResult) -> list[str]:
    categories: list[str] = []
    for rule_id in result.hard_failures:
        category = _VALIDATOR_FAILURE_CATEGORY_BY_RULE.get(rule_id, rule_id)
        _append_unique(categories, category)
    return categories


def _append_unique(items: list[str], value: str | None) -> None:
    if value and value not in items:
        items.append(value)


def _normalize_semantic_guard_mode(mode: SemanticGuardMode | str) -> SemanticGuardMode:
    if isinstance(mode, SemanticGuardMode):
        return mode
    try:
        return SemanticGuardMode(str(mode).lower())
    except ValueError as exc:
        raise ValueError("semantic_guard_mode must be one of: off, auto, required") from exc


def _selected_semantic_judge_model(model: str | None) -> str:
    return model or app_settings.semantic_judge_model or "deepseek-v4-flash"


def _selected_semantic_judge_base_url(base_url: str | None) -> str:
    return base_url or app_settings.semantic_judge_base_url or app_settings.llm_base_url


def _run_semantic_guard_for_case(
    case: Any,
    agent_output: dict[str, Any] | None,
    *,
    mode: str,
    semantic_guard_mode: SemanticGuardMode,
    semantic_judge_client: "LLMClient | None",
    semantic_judge_model: str,
    semantic_judge_base_url: str,
    cache_dir: Path,
    use_cache: bool,
) -> SemanticGuardReport:
    judge_factory = None
    if (
        mode == "real"
        and semantic_guard_mode != SemanticGuardMode.off
        and semantic_judge_client is None
    ):
        judge_factory = lambda: build_semantic_judge_client(
            model=semantic_judge_model,
            base_url=semantic_judge_base_url,
        )
    try:
        return run_semantic_guard(
            case_id=case.id,
            module=case.module,
            agent_output=agent_output,
            workspace_state=case.workspace_state,
            mode=semantic_guard_mode,
            judge_client=semantic_judge_client,
            cache_dir=cache_dir,
            use_cache=use_cache,
            judge_model=semantic_judge_model,
            judge_client_factory=judge_factory,
        )
    except Exception as exc:
        return SemanticGuardReport(
            mode=semantic_guard_mode,
            error_message=f"semantic guard failed: {type(exc).__name__}",
        )


# ---------------------------------------------------------------------------
# Suite runner
# ---------------------------------------------------------------------------

# Default max parallel workers.  Conservative default (4) to avoid
# overwhelming the LLM API or tripping rate limits while still giving a
# large speedup over serial execution (12 cases × ~2 calls each).
_DEFAULT_WORKERS = 4


def _run_one_case(
    case: Any,
    *,
    mode: str,
    model: str,
    run_id: str,
    output_dir: Path,
    runs_per_case: int = 1,
    judge_mode: str = "auto",
    cache_dir: Path | None = None,
    use_cache: bool = False,
    cache_context: dict[str, Any] | None = None,
    semantic_guard_mode: SemanticGuardMode = SemanticGuardMode.auto,
    semantic_judge_model: str = "",
    semantic_judge_base_url: str = "",
    projectflow_root: str = "",
) -> CaseReport:
    """Worker: run a single case (including multi-run stability) in a thread.

    Each thread creates its own ``LLMClient`` so that the httpx connection
    pool stays local to the thread.
    """
    from app.agent.llm_client import build_agent_llm_client

    llm_client = build_agent_llm_client() if mode == "real" else None

    all_run_reports: list[CaseReport] = []
    try:
        for run_idx in range(runs_per_case):
            report = run_case(
                case,
                mode=mode,
                llm_client=llm_client,
                model=model,
                judge_mode=judge_mode,
                cache_dir=cache_dir,
                use_cache=use_cache,
                cache_context=cache_context,
                semantic_guard_mode=semantic_guard_mode,
                semantic_judge_model=semantic_judge_model,
                semantic_judge_base_url=semantic_judge_base_url,
                projectflow_root=projectflow_root,
            )
            report.run_id = run_id
            (output_dir / case.id).mkdir(parents=True, exist_ok=True)
            write_case_report(
                report,
                output_dir / case.id,
                filename=f"run_{run_idx}.report.json",
            )
            all_run_reports.append(report)
    finally:
        if hasattr(llm_client, "close"):
            llm_client.close()

    if runs_per_case > 1:
        report = _compute_multi_run_report(case.id, all_run_reports, model)
    else:
        report = all_run_reports[0]

    report.run_id = run_id
    report.output_path = write_case_report(report, output_dir)
    return report


def run_suite(
    fixtures_dir: str,
    *,
    mode: str = "mock",
    output_dir: str | Path | None = None,
    model: str = "",
    llm_client: Any = None,
    runs_per_case: int = 1,
    workers: int = _DEFAULT_WORKERS,
    judge_mode: str = "auto",
    case_ids: list[str] | None = None,
    cache_dir: str | Path | None = None,
    use_cache: bool | None = None,
    resume_from: str | Path | None = None,
    retry_failed_from: str | Path | None = None,
    retry_errors_from: str | Path | None = None,
    semantic_guard_mode: SemanticGuardMode | str = SemanticGuardMode.auto,
    semantic_judge_model: str = "",
    semantic_judge_base_url: str = "",
    projectflow_root: str = "",
) -> tuple[list[CaseReport], SuiteSummary]:
    """Load fixtures, run each case, and produce reports.

    Cases are executed concurrently via ``ThreadPoolExecutor`` so that the
    total wall-clock time is dominated by the slowest case rather than the
    sum of all cases (~5× improvement for 12 cases on glm-5.1).

    Returns ``(reports, summary)``.
    """
    cases = load_fixtures(fixtures_dir)
    if case_ids:
        wanted = set(case_ids)
        cases = [case for case in cases if case.id in wanted]
        missing = sorted(wanted - {case.id for case in cases})
        if missing:
            raise ValueError(f"Unknown benchmark case id(s): {', '.join(missing)}")
        if not cases:
            raise ValueError("No benchmark cases selected")

    retry_from, retry_mode = _select_retry_source(
        retry_failed_from=retry_failed_from,
        retry_errors_from=retry_errors_from,
    )
    if retry_from:
        retry_case_ids = _case_ids_for_retry(Path(retry_from), retry_mode)
        cases = [case for case in cases if case.id in retry_case_ids]
        if not cases:
            raise ValueError(f"No benchmark cases selected by retry mode: {retry_mode}")

    resume_reports_by_id = (
        _load_reports_map_from_dir(Path(resume_from)) if resume_from else {}
    )
    run_id = _generate_run_id(model, mode)
    output_dir = Path(output_dir or OUTPUT_BASE / run_id)
    selected_cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
    cache_enabled = mode == "real" and ((mode == "real") if use_cache is None else use_cache)
    selected_semantic_guard_mode = _normalize_semantic_guard_mode(semantic_guard_mode)
    selected_semantic_judge_model = _selected_semantic_judge_model(semantic_judge_model)
    selected_semantic_judge_base_url = _selected_semantic_judge_base_url(semantic_judge_base_url)

    # Resolve external ProjectFlow agent metadata.
    # Prefer .sync_meta.json (written by `pfae sync`) which includes dirty state.
    resolved_projectflow_root = ""
    projectflow_git_commit = ""
    sync_meta_path = Path(__file__).resolve().parents[1] / "agent" / ".sync_meta.json"
    if sync_meta_path.is_file():
        try:
            sync_meta = json.loads(sync_meta_path.read_text())
            commit = sync_meta.get("commit", "")
            dirty = sync_meta.get("dirty") == "true"
            projectflow_git_commit = f"{commit}+dirty" if dirty and commit else commit
            resolved_projectflow_root = sync_meta.get("source_path", "")
        except Exception:
            logger.warning("Failed to read sync metadata from %s", sync_meta_path)
    elif projectflow_root:
        resolved_projectflow_root = str(Path(projectflow_root).resolve())
        try:
            result = subprocess.run(
                ["git", "-C", resolved_projectflow_root, "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                projectflow_git_commit = result.stdout.strip()
        except Exception:
            logger.warning("Failed to resolve git commit for %s", resolved_projectflow_root)

    config = RunConfig(
        mode=mode,
        model=model,
        provider=os.getenv("LLM_PROVIDER", ""),
        base_url_host=_host_from_base_url(os.getenv("LLM_BASE_URL", "")),
        cache_enabled=cache_enabled,
        cache_dir=str(selected_cache_dir) if cache_enabled else "",
        resume_from=str(resume_from or ""),
        retry_from=str(retry_from or ""),
        retry_mode=retry_mode,
        output_dir=str(output_dir),
        runs_per_case=runs_per_case,
        judge_mode=judge_mode,
        case_ids=[case.id for case in cases] if case_ids else [],
        semantic_guard_mode=selected_semantic_guard_mode,
        semantic_judge_model=selected_semantic_judge_model,
        semantic_judge_base_url_host=_host_from_base_url(selected_semantic_judge_base_url),
        semantic_judge_prompt_version=SEMANTIC_JUDGE_PROMPT_VERSION,
        projectflow_source_path=resolved_projectflow_root,
        projectflow_git_commit=projectflow_git_commit,
        agent_model=model,
    )

    start = time.monotonic()

    # ── run cases in parallel ────────────────────────────────────────
    # mock mode doesn't need parallelism, but it's fast anyway.
    skipped_reports: dict[str, CaseReport] = {
        case.id: resume_reports_by_id[case.id]
        for case in cases
        if case.id in resume_reports_by_id
    }
    cases_to_run = [case for case in cases if case.id not in skipped_reports]

    actual_workers = min(workers, len(cases_to_run)) if mode == "real" and cases_to_run else 1
    logger.info(
        "Running %d cases with %d workers (mode=%s)",
        len(cases_to_run),
        actual_workers,
        mode,
    )

    reports_by_id: dict[str, CaseReport] = dict(skipped_reports)
    if cases_to_run:
        with concurrent.futures.ThreadPoolExecutor(max_workers=actual_workers) as executor:
            future_to_case = {
                executor.submit(
                    _run_one_case,
                    case,
                    mode=mode,
                    model=model,
                    run_id=run_id,
                    output_dir=output_dir,
                    runs_per_case=runs_per_case,
                    judge_mode=judge_mode,
                    cache_dir=selected_cache_dir,
                    use_cache=cache_enabled,
                    semantic_guard_mode=selected_semantic_guard_mode,
                    semantic_judge_model=selected_semantic_judge_model,
                    semantic_judge_base_url=selected_semantic_judge_base_url,
                    projectflow_root=projectflow_root,
                ): case
                for case in cases_to_run
            }
            for future in concurrent.futures.as_completed(future_to_case):
                case = future_to_case[future]
                try:
                    report = future.result()
                except Exception as exc:
                    logger.exception(
                        "Case %s failed with unhandled exception: %s", case.id, exc
                    )
                    # Synthesize a minimal failure report so the suite still finishes
                    report = CaseReport(
                        run_id=run_id,
                        case_id=case.id,
                        module=case.module,
                        model=model,
                        status=CaseStatus.failed,
                        hard_failures=[],
                        overall_score=0.0,
                        agent_status="failed",
                        error_message=str(exc),
                    )
                reports_by_id[report.case_id] = report

    for report in skipped_reports.values():
        report.run_id = run_id
        report.output_path = write_case_report(report, output_dir)

    # Preserve the original fixture order in the report list
    reports = [reports_by_id[c.id] for c in cases]

    duration = time.monotonic() - start

    summary = build_suite_summary(
        run_id,
        reports,
        config=config,
        duration_seconds=duration,
        skipped_cases=len(skipped_reports),
    )
    summary.timestamp = datetime.now(timezone.utc).isoformat()

    # Write suite artifacts
    write_suite_summary(summary, output_dir)
    write_markdown_summary(summary, reports, output_dir)
    _append_run_history(summary, output_dir)

    return reports, summary


def _append_run_history(summary: SuiteSummary, output_dir: Path) -> None:
    """Append a one-line summary to the shared HISTORY.md file."""
    history_path = output_dir.parent / "HISTORY.md"
    commit = summary.config.projectflow_git_commit if summary.config else ""
    commit_short = commit[:12] if commit else "-"
    top_failures = ", ".join(summary.top_failure_categories[:3]) if summary.top_failure_categories else "-"

    is_new = not history_path.exists()
    with open(history_path, "a", encoding="utf-8") as f:
        if is_new:
            f.write("# Benchmark Run History\n\n")
            f.write("| Run ID | Mode | Cases | Score | HF | Time | PF Commit | Top Failures |\n")
            f.write("|--------|------|-------|-------|----|------|-----------|-------------|\n")
        f.write(
            f"| {summary.run_id} | {summary.config.mode if summary.config else '?'} "
            f"| {summary.cases_passed}/{summary.cases_total} "
            f"| {summary.average_score:.3f} "
            f"| {summary.hard_failure_count} "
            f"| {summary.duration_seconds:.0f}s "
            f"| {commit_short} "
            f"| {top_failures} |\n"
        )


def _compute_stability_stats(run_reports: list) -> dict:
    scores = [r.overall_score for r in run_reports]
    passed = sum(1 for r in run_reports if r.status.value == "passed")
    total = len(run_reports)
    pass_at_1 = passed / max(total, 1)
    pass_k = pass_at_1 ** min(total, 5)
    mean = sum(scores) / max(len(scores), 1)
    variance = sum((s - mean) ** 2 for s in scores) / max(len(scores), 1)
    assertion_fail_counts: dict[str, int] = {}
    for r in run_reports:
        for ar in r.assertion_results:
            if ar.status == "failed":
                assertion_fail_counts[ar.assertion_id] = assertion_fail_counts.get(ar.assertion_id, 0) + 1
    flaky = [aid for aid, cnt in assertion_fail_counts.items() if 0 < cnt < total]
    return {
        "pass_at_1": round(pass_at_1, 4),
        "pass_k": round(pass_k, 4),
        "score_mean": round(mean, 4),
        "score_variance": round(variance, 6),
        "flaky_assertions": flaky,
        "num_runs": total,
        "num_passed": passed,
    }


def _load_reports_map_from_dir(dir_path: Path) -> dict[str, CaseReport]:
    if not dir_path.is_dir():
        raise ValueError(f"Run directory not found: {dir_path}")
    reports: dict[str, CaseReport] = {}
    for report in _load_reports_from_dir(dir_path):
        reports[report.case_id] = report
    return reports


def _select_retry_source(
    *,
    retry_failed_from: str | Path | None,
    retry_errors_from: str | Path | None,
) -> tuple[Path | None, str]:
    selected = [
        (Path(retry_failed_from), "failed") if retry_failed_from else None,
        (Path(retry_errors_from), "errors") if retry_errors_from else None,
    ]
    active = [item for item in selected if item is not None]
    if len(active) > 1:
        raise ValueError("Use only one retry mode at a time")
    return active[0] if active else (None, "")


def _case_ids_for_retry(run_dir: Path, retry_mode: str) -> set[str]:
    reports = _load_reports_map_from_dir(run_dir)
    selected: set[str] = set()
    for case_id, report in reports.items():
        if retry_mode == "failed" and report.status != CaseStatus.passed:
            selected.add(case_id)
        elif retry_mode == "errors" and _is_error_retry_candidate(report):
            selected.add(case_id)
    return selected


def _is_error_retry_candidate(report: CaseReport) -> bool:
    return (
        report.status in {CaseStatus.error, CaseStatus.judge_failed}
        or report.agent_status == "failed"
        or bool(report.error_message)
    )


def _compute_multi_run_report(case_id: str, run_reports: list, model: str):
    from app.agent_eval.schemas import CaseStatus
    base = run_reports[-1]
    stability = _compute_stability_stats(run_reports)
    multi_run_pass = stability["pass_at_1"] >= 0.8
    base.stability = stability
    base.case_pass = multi_run_pass and base.status == CaseStatus.passed
    if not multi_run_pass and base.status == CaseStatus.passed:
        base.status = CaseStatus.failed
    return base


def _generate_run_id(model: str = "", mode: str = "mock") -> str:
    """Generate a unique run ID."""
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    model_slug = model.replace("/", "-").replace(".", "-") if model else mode
    short_id = uuid.uuid4().hex[:6]
    return f"{ts}-{model_slug}-{short_id}"


def _host_from_base_url(base_url: str) -> str:
    if not base_url:
        return ""
    parsed = urlparse(base_url)
    return parsed.netloc or parsed.path.split("/")[0]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ProjectFlow Agent Evaluation Benchmark Runner",
    )
    sub = parser.add_subparsers(dest="command", help="Sub-command")

    # Run command
    run_parser = sub.add_parser("run", help="Run the evaluation suite")
    run_parser.add_argument(
        "--fixtures",
        default="app/agent_eval/fixtures",
        help="Path to fixture JSON directory",
    )
    run_parser.add_argument(
        "--mode",
        default="mock",
        choices=["mock", "real"],
        help="Runner mode: mock (stub) or real (LLM)",
    )
    run_parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for reports (default: output/agent-eval/<run-id>)",
    )
    run_parser.add_argument(
        "--model",
        default="stub",
        help="Model name for reporting",
    )
    run_parser.add_argument(
        "--runs-per-case",
        type=int,
        default=1,
        help="Number of runs per case for stability (default: 1)",
    )
    run_parser.add_argument(
        "--workers",
        type=int,
        default=_DEFAULT_WORKERS,
        help=f"Max parallel workers for real mode (default: {_DEFAULT_WORKERS})",
    )
    run_parser.add_argument(
        "--judge-mode",
        default="auto",
        choices=["auto", "llm", "stub"],
        help="Judge strategy for real mode: auto skips covered cases, llm always calls LLM judge, stub never calls LLM judge",
    )
    run_parser.add_argument(
        "--semantic-guard",
        default="auto",
        choices=["off", "auto", "required"],
        help="Semantic guard mode: off, auto, or required (default: auto)",
    )
    run_parser.add_argument(
        "--semantic-judge-model",
        default="",
        help="Lite semantic judge model (default: settings/env SEMANTIC_JUDGE_MODEL)",
    )
    run_parser.add_argument(
        "--semantic-judge-base-url",
        default="",
        help="Lite semantic judge base URL; API keys are read from environment/settings only",
    )
    run_parser.add_argument(
        "--case-filter",
        default="",
        help="Comma-separated case IDs to run for focused iteration",
    )
    run_parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_CACHE_DIR),
        help=f"Agent output cache directory (default: {DEFAULT_CACHE_DIR})",
    )
    run_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable real-mode Agent output cache",
    )
    run_parser.add_argument(
        "--resume",
        default="",
        help="Resume from an existing run directory, or 'latest'",
    )
    run_parser.add_argument(
        "--retry-failed",
        default="",
        help="Run only cases that failed in an existing run directory, or 'latest'",
    )
    run_parser.add_argument(
        "--retry-errors",
        default="",
        help="Run only cases with infrastructure/judge errors in an existing run directory, or 'latest'",
    )

    # Compare command
    compare_parser = sub.add_parser("compare", help="Compare two runs")
    compare_parser.add_argument(
        "baseline_dir",
        help="Baseline run output directory",
    )
    compare_parser.add_argument(
        "candidate_dir",
        help="Candidate run output directory",
    )
    compare_parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for diff report",
    )

    # List fixtures command
    list_parser = sub.add_parser("list-fixtures", help="List available fixture IDs")
    list_parser.add_argument(
        "--fixtures",
        default="app/agent_eval/fixtures",
        help="Path to fixture JSON directory",
    )

    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    case_ids = _parse_case_filter(args.case_filter)
    reports, summary = run_suite(
        args.fixtures,
        mode=args.mode,
        output_dir=args.output_dir,
        model=args.model,
        runs_per_case=args.runs_per_case,
        workers=args.workers,
        judge_mode=args.judge_mode,
        case_ids=case_ids,
        cache_dir=args.cache_dir,
        use_cache=not args.no_cache,
        resume_from=_resolve_run_ref(args.resume),
        retry_failed_from=_resolve_run_ref(args.retry_failed),
        retry_errors_from=_resolve_run_ref(args.retry_errors),
        semantic_guard_mode=args.semantic_guard,
        semantic_judge_model=args.semantic_judge_model,
        semantic_judge_base_url=args.semantic_judge_base_url,
    )

    print(f"\n{'='*60}")
    print(f"  Run ID:      {summary.run_id}")
    print(f"  Model:       {summary.model}")
    print(f"  Workers:     {args.workers}")
    print(f"  Judge Mode:  {args.judge_mode}")
    if summary.config:
        print(f"  Semantic:    {summary.config.semantic_guard_mode.value}")
    print(f"  Cache:       {summary.cache_hits} hit / {summary.cache_misses} miss")
    print(f"  Skipped:     {summary.skipped_cases}")
    print(f"  Cases:       {summary.cases_passed}/{summary.cases_total} passed")
    print(f"  Avg Score:   {summary.average_score:.3f}")
    print(f"  Hard Fails:  {summary.hard_failure_count}")
    print(f"  Duration:    {summary.duration_seconds:.1f}s")
    print(f"{'='*60}\n")

    # Print per-case summary with assertion info
    for rep in sorted(reports, key=lambda r: r.case_id):
        icon = "[OK]" if rep.status.value == "passed" else "[FAIL]"
        hf = f" [HF: {','.join(rep.hard_failures)}]" if rep.hard_failures else ""
        af = f" [AS: {rep.hard_fail_count} hard]" if rep.hard_fail_count > 0 else ""
        ws = f" [WS: {rep.weighted_score:.2f}]" if hasattr(rep, 'weighted_score') and rep.weighted_score != rep.overall_score else ""
        sg = ""
        if rep.semantic_guard:
            if rep.semantic_guard.hard_failures:
                sg = f" [SG: {len(rep.semantic_guard.hard_failures)} hard]"
            elif rep.semantic_guard.uncertain_count:
                sg = f" [SG: {rep.semantic_guard.uncertain_count} uncertain]"
        print(f"  {icon} {rep.case_id:35s} {rep.overall_score:.2f} {rep.status.value}{hf}{af}{ws}{sg}")

    print()

    # Output path
    if reports:
        print(f"  Reports written to: {Path(reports[0].output_path).parent}")
    print()

    return 0 if summary.cases_failed == 0 and summary.cases_judge_failed == 0 else 1


def _parse_case_filter(raw: str) -> list[str] | None:
    case_ids = [part.strip() for part in raw.split(",") if part.strip()]
    return case_ids or None


def _resolve_run_ref(raw: str) -> Path | None:
    if not raw:
        return None
    if raw != "latest":
        return Path(raw)
    candidates = [
        path for path in OUTPUT_BASE.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ] if OUTPUT_BASE.exists() else []
    if not candidates:
        raise ValueError(f"No benchmark run directories found in {OUTPUT_BASE}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _cmd_compare(args: argparse.Namespace) -> int:
    baseline_path = Path(args.baseline_dir)
    candidate_path = Path(args.candidate_dir)

    if not baseline_path.is_dir():
        print(f"Error: baseline directory not found: {baseline_path}", file=sys.stderr)
        return 1
    if not candidate_path.is_dir():
        print(f"Error: candidate directory not found: {candidate_path}", file=sys.stderr)
        return 1

    # Load summaries
    baseline_summary_path = baseline_path / "suite_summary.json"
    candidate_summary_path = candidate_path / "suite_summary.json"

    if not baseline_summary_path.exists():
        print(f"Error: baseline summary not found: {baseline_summary_path}", file=sys.stderr)
        return 1
    if not candidate_summary_path.exists():
        print(f"Error: candidate summary not found: {candidate_summary_path}", file=sys.stderr)
        return 1

    from app.agent_eval.schemas import SuiteSummary
    baseline_summary = SuiteSummary(**json.loads(baseline_summary_path.read_text(encoding="utf-8")))
    candidate_summary = SuiteSummary(**json.loads(candidate_summary_path.read_text(encoding="utf-8")))

    # Load reports
    baseline_reports = _load_reports_from_dir(baseline_path)
    candidate_reports = _load_reports_from_dir(candidate_path)

    diff = compare_runs(baseline_summary, candidate_summary, baseline_reports, candidate_reports)

    output_dir = Path(args.output_dir) if args.output_dir else candidate_path / "diff"
    output_dir.mkdir(parents=True, exist_ok=True)

    diff_path = output_dir / "diff_report.json"
    diff_path.write_text(diff.model_dump_json(indent=2), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"  Comparison: {diff.baseline_run_id} -> {diff.candidate_run_id}")
    if diff.baseline_commit or diff.candidate_commit:
        base_label = diff.baseline_commit or "unknown"
        cand_label = diff.candidate_commit or "unknown"
        print(f"  ProjectFlow: {base_label} -> {cand_label}")
        if diff.version_changed:
            print(f"  ** Version changed **")
    print(f"  Average Delta: {diff.average_score_delta:+.4f}")
    print(f"  Regression Passed: {'Y' if diff.regression_passed else 'N'}")
    print(f"{'='*60}\n")

    if diff.regression_notes:
        print("  Notes:")
        for note in diff.regression_notes:
            print(f"    - {note}")
        print()

    if diff.new_hard_failures_by_case:
        print("  New Hard Failures:")
        for case_id, failures in diff.new_hard_failures_by_case.items():
            print(f"    - {case_id}: {', '.join(failures)}")
        print()

    if diff.fixed_hard_failures_by_case:
        print("  Fixed Hard Failures:")
        for case_id, failures in diff.fixed_hard_failures_by_case.items():
            print(f"    - {case_id}: {', '.join(failures)}")
        print()

    print(f"  Diff report: {diff_path}")
    print()

    return 0 if diff.regression_passed else 1


def _load_reports_from_dir(dir_path: Path) -> list[CaseReport]:
    """Load all case report JSON files from a directory."""
    reports: list[CaseReport] = []
    for fpath in sorted(dir_path.glob("*.report.json")):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            reports.append(CaseReport(**data))
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Failed to load report %s: %s", fpath, exc)
    return reports


def _cmd_list_fixtures(args: argparse.Namespace) -> int:
    try:
        ids = list_fixture_ids(args.fixtures)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Fixtures in {args.fixtures}:")
    for fid in ids:
        print(f"  - {fid}")
    print(f"\nTotal: {len(ids)} fixture(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the benchmark CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    if args.command == "run":
        return _cmd_run(args)
    elif args.command == "compare":
        return _cmd_compare(args)
    elif args.command == "list-fixtures":
        return _cmd_list_fixtures(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
