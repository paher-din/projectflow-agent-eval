"""Deterministic validators for Agent Evaluation Benchmark.

Each validator receives the case definition, agent output (as a raw dict),
and agent run metadata, and returns a ``ValidatorFinding``.

Hard-fail rules override LLM judge scores when they fail.
"""

from __future__ import annotations

from typing import Any

from app.agent_eval.semantic_guard import DEFAULT_SCOPE_CONTRACT, extract_scope_candidates
from app.agent_eval.schemas import EvalCase, HardFailRule, ValidatorResult
from app.agent_eval.schemas import SemanticCandidateDecision


def run_all_validators(
    case: EvalCase,
    agent_output: dict[str, Any] | None,
    *,
    agent_status: str = "",
    raw_agent_output: str | None = None,
    workspace_state: dict[str, Any] | None = None,
) -> ValidatorResult:
    """Run all deterministic validators against the agent output for a case.

    Parameters
    ----------
    case
        The benchmark case fixture.
    agent_output
        Parsed agent output dict (or ``None`` if the agent failed entirely).
    agent_status
        Agent run status string: ``"success"``, ``"repaired"``, ``"fallback"``, ``"failed"``.
    raw_agent_output
        Raw text output from the agent (used by fallback validators).
    workspace_state
        The workspace state as-supplied to the agent (for grounding checks).

    Returns
    -------
    ValidatorResult
        Aggregated findings with hard/soft failure lists.
    """
    result = ValidatorResult()
    hard_rules = set(case.hard_fail_rules)

    # Determine which validators to run based on hard_fail_rules
    for rule in HardFailRule:
        rule_id = rule.value
        severity = "hard" if rule_id in hard_rules else "soft"

        if rule_id == "invalid_schema":
            _check_invalid_schema(result, agent_output, agent_status, severity)
        elif rule_id == "missing_status":
            _check_missing_status(result, agent_status, severity)
        elif rule_id == "fabricated_workspace_entity":
            _check_fabricated_entity(result, agent_output, workspace_state or case.workspace_state, severity)
        elif rule_id == "violates_mvp_boundary":
            _check_violates_mvp_boundary(result, agent_output, workspace_state or case.workspace_state, severity)
        elif rule_id == "unsafe_persistence":
            _check_unsafe_persistence(result, agent_output, severity)
        elif rule_id == "negotiate_created_generic_proposal":
            _check_negotiate_generic_proposal(result, agent_output, case, severity)
        elif rule_id == "missing_reason":
            _check_missing_reason(result, agent_output, severity)
        elif rule_id == "empty_fallback":
            _check_empty_fallback(result, agent_output, agent_status, raw_agent_output, severity)
        elif rule_id == "date_miscalculation":
            _check_date_miscalculation(result, agent_output, workspace_state or case.workspace_state, severity)
        elif rule_id == "unlabeled_fallback":
            _check_unlabeled_fallback(result, agent_status, severity)

    return result


# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------


def _check_invalid_schema(
    result: ValidatorResult,
    agent_output: dict[str, Any] | None,
    agent_status: str,
    severity: str,
) -> None:
    """Check that agent output is not None and has valid structure."""
    passed = agent_output is not None and isinstance(agent_output, dict)
    detail = ""
    if not passed:
        detail = f"Agent output is {type(agent_output).__name__}, expected dict"
    result.add_finding(
        rule_id="invalid_schema",
        severity=severity,
        passed=passed,
        detail=detail,
    )


def _check_missing_status(
    result: ValidatorResult,
    agent_status: str,
    severity: str,
) -> None:
    """Check that agent_status is present and meaningful."""
    passed = bool(agent_status) and agent_status in ("success", "repaired", "fallback", "failed")
    detail = f"agent_status='{agent_status}'" if agent_status else "agent_status is empty"
    result.add_finding(
        rule_id="missing_status",
        severity=severity,
        passed=passed,
        detail=detail if not passed else "",
    )


def _check_fabricated_entity(
    result: ValidatorResult,
    agent_output: dict[str, Any] | None,
    workspace_state: dict[str, Any],
    severity: str,
) -> None:
    """Check for references to entities not present in WorkspaceState."""
    if not agent_output or not isinstance(agent_output, dict):
        result.add_finding("fabricated_workspace_entity", severity, True, detail="No output to check")
        return

    # Collect known entity IDs from workspace_state
    known: set[str] = set()

    # Member user_ids
    for m in workspace_state.get("members", []):
        uid = m.get("user_id", "")
        if uid:
            known.add(uid)
        name = m.get("display_name", "")
        if name:
            known.add(name)

    # Project members
    proj = workspace_state.get("project", {})
    if proj:
        pid = proj.get("id", "")
        if pid:
            known.add(pid)
        for s in proj.get("stages", []):
            sid = s.get("id", "")
            if sid:
                known.add(sid)
            sname = s.get("name", "")
            if sname:
                known.add(sname)
        for t in proj.get("tasks", []):
            tid = t.get("id", "")
            if tid:
                known.add(tid)
        for r in proj.get("resources", []):
            rid = r.get("id", "")
            if rid:
                known.add(rid)
        for p in proj.get("assignment_proposals", []):
            pid2 = p.get("id", "")
            if pid2:
                known.add(pid2)

    # Serialize output text for scanning
    output_text = str(agent_output)

    # Check for unknown ID-like references (words like "user-N", "task-N", "stage-N")
    import re

    full_id_pattern = re.compile(r'\b[a-z]+-\d+\b')
    found_full_ids = set(full_id_pattern.findall(output_text))

    fabricated = found_full_ids - known
    # Filter out common false positives
    fabricated = {f for f in fabricated if not f.startswith("p0") and not f.startswith("p1")}

    # For breakdown outputs, new task IDs are valid — they're being created by the agent
    tasks_list = agent_output.get("tasks") if isinstance(agent_output, dict) else None
    if isinstance(tasks_list, list):
        new_task_ids = {t["id"] for t in tasks_list if isinstance(t, dict) and t.get("id")}
        fabricated -= new_task_ids

    passed = len(fabricated) == 0
    detail = ""
    if not passed:
        detail = f"References entities not in WorkspaceState: {', '.join(sorted(fabricated))}"
    result.add_finding("fabricated_workspace_entity", severity, passed, detail)


def _check_violates_mvp_boundary(
    result: ValidatorResult,
    agent_output: dict[str, Any] | None,
    workspace_state: dict[str, Any],
    severity: str,
) -> None:
    """Check for out-of-scope MVP features."""
    if not agent_output or not isinstance(agent_output, dict):
        result.add_finding("violates_mvp_boundary", severity, True, detail="No output to check")
        return

    candidates = extract_scope_candidates(agent_output, DEFAULT_SCOPE_CONTRACT)
    matches = sorted({
        candidate.span
        for candidate in candidates
        if candidate.deterministic_decision == SemanticCandidateDecision.fail
    })
    passed = not matches
    detail = f"References out-of-MVP items: {', '.join(matches)}" if matches else ""
    result.add_finding("violates_mvp_boundary", severity, passed, detail)


def _check_unsafe_persistence(
    result: ValidatorResult,
    agent_output: dict[str, Any] | None,
    severity: str,
) -> None:
    """Check that high-impact output does not bypass proposal/confirmation."""
    if not agent_output or not isinstance(agent_output, dict):
        result.add_finding("unsafe_persistence", severity, True, detail="No output to check")
        return

    # If requires_confirmation is explicitly set to False for a type that should have it, that's unsafe
    requires_conf = agent_output.get("requires_confirmation")
    if requires_conf is False:
        passed = False
        detail = "Output sets requires_confirmation=False, bypassing human confirmation"
        result.add_finding("unsafe_persistence", severity, passed, detail)
        return

    result.add_finding("unsafe_persistence", severity, True, detail="")


def _check_negotiate_generic_proposal(
    result: ValidatorResult,
    agent_output: dict[str, Any] | None,
    case: EvalCase,
    severity: str,
) -> None:
    """Check that negotiate output does not create a generic AgentProposal."""
    if case.module != "negotiate":
        # Only relevant for negotiate module
        result.add_finding("negotiate_created_generic_proposal", severity, True, detail="Not a negotiate case")
        return

    if not agent_output or not isinstance(agent_output, dict):
        result.add_finding("negotiate_created_generic_proposal", severity, True, detail="No output to check")
        return

    # Check for generic proposal patterns that shouldn't exist in negotiate output
    output_text = str(agent_output).lower()

    # Allow "requires_confirmation" through since it exists on many outputs
    # But check for direction-card-like structures
    has_direction_card_like = all(kw in output_text for kw in ["problem", "users", "value"])
    has_stage_plan_like = "stages" in output_text and isinstance(agent_output.get("stages"), list)

    passed = not has_direction_card_like and not has_stage_plan_like
    detail = ""
    if not passed:
        detail = "Negotiate output contains direction-card or stage-plan-like structure (should be timeline-only)"
    result.add_finding("negotiate_created_generic_proposal", severity, passed, detail)


def _check_missing_reason(
    result: ValidatorResult,
    agent_output: dict[str, Any] | None,
    severity: str,
) -> None:
    """Check that output contains a reason or evidence field."""
    if not agent_output or not isinstance(agent_output, dict):
        result.add_finding("missing_reason", severity, True, detail="No output to check")
        return

    has_reason = bool(agent_output.get("reason"))
    has_evidence = bool(agent_output.get("evidence"))
    has_suggestion = bool(agent_output.get("suggestion"))
    has_swap_reasoning = bool(agent_output.get("swap_reasoning"))

    passed = has_reason or has_evidence or has_suggestion or has_swap_reasoning
    detail = ""
    if not passed:
        detail = "Output lacks reason, evidence, suggestion, or swap_reasoning field"
    result.add_finding("missing_reason", severity, passed, detail)


def _check_empty_fallback(
    result: ValidatorResult,
    agent_output: dict[str, Any] | None,
    agent_status: str,
    raw_agent_output: str | None,
    severity: str,
) -> None:
    """Check that fallback output is non-empty, Chinese, and actionable."""
    if agent_status != "fallback":
        # Not a fallback case — skip
        result.add_finding("empty_fallback", severity, True, detail="Not a fallback")
        return

    if not agent_output or not isinstance(agent_output, dict):
        result.add_finding("empty_fallback", severity, False, detail="Fallback output is None or not a dict")
        return

    # Check non-empty
    if not any(v for v in agent_output.values() if isinstance(v, str) and v.strip()):
        result.add_finding("empty_fallback", severity, False, detail="Fallback output contains no non-empty string values")
        return

    # Check Chinese presence
    output_text = str(agent_output)
    has_chinese = any("一" <= c <= "鿿" for c in output_text)
    if not has_chinese:
        result.add_finding("empty_fallback", severity, False, detail="Fallback output lacks Chinese text")
        return

    result.add_finding("empty_fallback", severity, True, detail="")


def _check_date_miscalculation(
    result: ValidatorResult,
    agent_output: dict[str, Any] | None,
    workspace_state: dict[str, Any],
    severity: str,
) -> None:
    """Check that output does not contradict provided current_date or timezone."""
    if not agent_output or not isinstance(agent_output, dict):
        result.add_finding("date_miscalculation", severity, True, detail="No output to check")
        return

    current_date_str = workspace_state.get("current_date", "")
    deadline_str = ""
    proj = workspace_state.get("project", {})
    if proj:
        deadline_str = proj.get("deadline", "")

    if not current_date_str:
        result.add_finding("date_miscalculation", severity, True, detail="No current_date in workspace_state to compare")
        return

    # Check stages in output for date contradictions
    stages = agent_output.get("stages", [])
    if isinstance(stages, list):
        for idx, stage in enumerate(stages):
            start = stage.get("start_date", "")
            end = stage.get("end_date", "")
            if start and start < current_date_str:
                result.add_finding(
                    "date_miscalculation", severity, False,
                    f"Stage '{stage.get('name', f'#{idx}')}' start_date {start} is before current_date {current_date_str}",
                )
                return
            if deadline_str and end and end > deadline_str:
                result.add_finding(
                    "date_miscalculation", severity, False,
                    f"Stage '{stage.get('name', f'#{idx}')}' end_date {end} is after deadline {deadline_str}",
                )
                return
            if start and end and end < start:
                result.add_finding(
                    "date_miscalculation", severity, False,
                    f"Stage '{stage.get('name', f'#{idx}')}' end_date {end} is before start_date {start}",
                )
                return

    result.add_finding("date_miscalculation", severity, True, detail="")


def _check_unlabeled_fallback(
    result: ValidatorResult,
    agent_status: str,
    severity: str,
) -> None:
    """Check that fallback is labeled and not presented as success."""
    if agent_status == "fallback":
        # It IS labeled as fallback, so pass
        result.add_finding("unlabeled_fallback", severity, True, detail="")
    elif agent_status == "":
        # No status at all
        result.add_finding("unlabeled_fallback", severity, False, detail="agent_status is empty, cannot determine if fallback was labeled")
    else:
        # success/repaired/failed is explicit enough
        result.add_finding("unlabeled_fallback", severity, True, detail="")
