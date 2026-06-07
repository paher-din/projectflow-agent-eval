"""Atomic assertion evaluation engine for v2 Agent Evaluation Benchmark.

Each evaluator function receives the assertion definition, agent output,
and workspace state, and returns an AssertionResult.

Deterministic evaluators run before any LLM semantic judge.
Hard assertion failures always fail the case regardless of weighted score.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.agent.output_schemas import AgentOutputValidationError, validate_agent_output
from app.agent_eval.schemas import (
    Assertion,
    AssertionResult,
    DEFAULT_PENALTY_MAP,
)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def evaluate_assertion(
    assertion: Assertion,
    agent_output: dict[str, Any] | None,
    *,
    agent_status: str = "",
    workspace_state: dict[str, Any] | None = None,
    raw_agent_output: str | None = None,
    timeline: list[dict[str, Any]] | None = None,
    entrypoint: str = "",
) -> AssertionResult:
    """Evaluate a single assertion using its configured evaluator."""
    evaluator = assertion.evaluator.value
    dispatch = {
        "schema": _eval_schema,
        "deterministic_text": _eval_deterministic_text,
        "deterministic_date": _eval_deterministic_date,
        "state_path": _eval_state_path,
        "graph": _eval_graph,
        "diff": _eval_diff,
        "trace": _eval_trace,
        "llm_semantic": _eval_llm_semantic,
    }
    fn = dispatch.get(evaluator, _eval_unknown)
    return fn(
        assertion,
        agent_output,
        agent_status=agent_status,
        workspace_state=workspace_state,
        raw_agent_output=raw_agent_output,
        timeline=timeline,
        entrypoint=entrypoint,
    )


def _make_result(
    assertion: Assertion,
    status: str,
    detail: str = "",
    evidence: list[dict[str, Any]] | None = None,
) -> AssertionResult:
    delta = 0.0
    if status == "failed":
        delta = DEFAULT_PENALTY_MAP.get(assertion.severity.value, 0.0)
    return AssertionResult(
        assertion_id=assertion.id,
        status=status,
        severity=assertion.severity,
        score_delta=delta,
        evidence=evidence or [],
        failure_category=assertion.failure_category,
        remediation_hint=assertion.remediation_hint,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Unknown evaluator
# ---------------------------------------------------------------------------


def _eval_unknown(
    assertion: Assertion,
    agent_output: dict[str, Any] | None,
    **kwargs: Any,
) -> AssertionResult:
    return _make_result(
        assertion,
        "skipped",
        detail=f"Unknown evaluator: {assertion.evaluator.value}",
    )


# ---------------------------------------------------------------------------
# schema evaluator
# ---------------------------------------------------------------------------


def _eval_schema(
    assertion: Assertion,
    agent_output: dict[str, Any] | None,
    **kwargs: Any,
) -> AssertionResult:
    rule = assertion.rule
    evidence: list[dict[str, Any]] = []

    if rule == "valid_json_contract":
        if agent_output is None:
            evidence.append({"path": "agent_output", "value": None})
            return _make_result(assertion, "failed", detail="Agent output is None", evidence=evidence)
        if not isinstance(agent_output, dict):
            return _make_result(assertion, "failed", detail=f"Agent output is {type(agent_output).__name__}, expected dict", evidence=evidence)
        event_type = _event_type_for_assertion(assertion, kwargs.get("entrypoint", ""))
        if event_type:
            try:
                validate_agent_output(event_type, agent_output)
            except AgentOutputValidationError as exc:
                evidence.append({"path": "agent_output", "value": str(exc)[:300]})
                return _make_result(
                    assertion,
                    "failed",
                    detail=f"{event_type} output failed Pydantic schema validation: {exc}",
                    evidence=evidence,
                )
        return _make_result(assertion, "passed")

    if rule == "no_empty_required_sections":
        if agent_output is None or not isinstance(agent_output, dict):
            return _make_result(assertion, "failed", detail="Cannot check sections: output is None or not a dict")
        required = assertion.required or []
        missing = []
        for field in required:
            val = agent_output.get(field)
            if val is None or (isinstance(val, (list, str)) and len(val) == 0):
                missing.append(field)
                evidence.append({"path": f"agent_output.{field}", "value": val})
        if missing:
            return _make_result(assertion, "failed", detail=f"Empty or missing required sections: {', '.join(missing)}", evidence=evidence)
        return _make_result(assertion, "passed")

    if rule == "proposal_shape_valid":
        if agent_output is None or not isinstance(agent_output, dict):
            return _make_result(assertion, "failed", detail="No output to check proposal shape")
        has_confirmation = agent_output.get("requires_confirmation") is True
        has_reason = bool(agent_output.get("reason"))
        if not has_confirmation or not has_reason:
            missing = []
            if not has_confirmation:
                missing.append("requires_confirmation=True")
            if not has_reason:
                missing.append("reason")
            return _make_result(assertion, "failed", detail=f"Proposal missing fields: {', '.join(missing)}", evidence=evidence)
        return _make_result(assertion, "passed")

    if rule == "structured_fields_nonempty":
        """Check that structured fields at nested paths are non-empty.

        Supports paths like cards[*].next_action, proposals[*].recommended_owner.
        [*] iterates over all items in a list at that level.
        """
        paths = assertion.required or []
        if not paths:
            return _make_result(assertion, "skipped", detail="No required paths specified")

        empty_fields: list[str] = []
        for path in paths:
            ok, err = _check_structured_path_nonempty(agent_output, path)
            if not ok:
                empty_fields.append(err)
                evidence.append({"path": path, "value": "empty or missing"})

        if empty_fields:
            return _make_result(
                assertion, "failed",
                detail=f"Empty or missing structured fields: {'; '.join(empty_fields)}",
                evidence=evidence,
            )
        return _make_result(assertion, "passed")

    return _make_result(assertion, "skipped", detail=f"Unknown schema rule: {rule}")

# ---------------------------------------------------------------------------
# deterministic_text evaluator
# ---------------------------------------------------------------------------


def _eval_deterministic_text(
    assertion: Assertion,
    agent_output: dict[str, Any] | None,
    **kwargs: Any,
) -> AssertionResult:
    if agent_output is None:
        return _make_result(assertion, "failed", detail="No output to check")

    output_text = str(agent_output)
    rule = assertion.rule
    evidence: list[dict[str, Any]] = []

    if rule == "forbidden_terms_absent":
        forbidden = assertion.forbidden or []
        findings = _find_unnegated_forbidden_terms(agent_output, forbidden)
        if findings:
            matches = sorted({term for term, _path in findings})
            for term, path in findings:
                evidence.append({"path": path, "value": f"found forbidden term: {term}"})
            return _make_result(
                assertion,
                "failed",
                detail=f"Forbidden terms found: {', '.join(matches)}",
                evidence=evidence,
            )
        return _make_result(assertion, "passed")

    if rule == "required_terms_present":
        required = assertion.required or []
        missing = [term for term in required if term.lower() not in output_text.lower()]
        if missing:
            for term in missing:
                evidence.append({"path": "agent_output.raw_text", "value": f"missing required term: {term}"})
            return _make_result(
                assertion,
                "failed",
                detail=f"Required terms missing: {', '.join(missing)}",
                evidence=evidence,
            )
        return _make_result(assertion, "passed")

    if rule == "regex_match":
        pattern = (assertion.payload or {}).get("pattern", "")
        if not pattern:
            return _make_result(assertion, "skipped", detail="No pattern in payload")
        if re.search(pattern, output_text, re.IGNORECASE):
            return _make_result(assertion, "passed")
        evidence.append({"path": "agent_output.raw_text", "value": f"no match for: {pattern}"})
        return _make_result(
            assertion,
            "failed",
            detail=f"Pattern not found: {pattern}",
            evidence=evidence,
        )

    if rule == "immutable_ids_not_in_proposal_context":
        immutable_ids = assertion.immutable_ids or []
        context_patterns = assertion.proposal_context_patterns or [
            "task_id", "assignee_id", "recommended_owner", "建议分配", "推荐由",
            "修改", "调整", "change", "modify", "reopen", "重新打开",
        ]
        if not immutable_ids:
            return _make_result(assertion, "skipped", detail="No immutable_ids configured")
        # Combine all context patterns into one regex
        context_re = re.compile("|".join(re.escape(p) for p in context_patterns), re.IGNORECASE)
        violations: list[dict[str, Any]] = []
        for eid in immutable_ids:
            eid_re = re.compile(re.escape(eid))
            for match in eid_re.finditer(output_text):
                pos = match.start()
                # Check if any context pattern appears within 300 chars
                window = output_text[max(0, pos - 150):pos + 150]
                ctx_match = context_re.search(window)
                if ctx_match:
                    violations.append({
                        "immutable_id": eid,
                        "position": pos,
                        "context_pattern": ctx_match.group(0),
                        "excerpt": window[max(0, ctx_match.start() - 40):ctx_match.end() + 40],
                    })
        if violations:
            for v in violations:
                evidence.append({
                    "path": "agent_output.raw_text",
                    "value": f"immutable {v['immutable_id']} near '{v['context_pattern']}': {v['excerpt'][:120]}",
                })
            ids = sorted({v["immutable_id"] for v in violations})
            return _make_result(
                assertion, "failed",
                detail=f"Immutable IDs referenced in proposal context: {', '.join(ids)}",
                evidence=evidence,
            )
        return _make_result(assertion, "passed")

    return _make_result(assertion, "skipped", detail=f"Unknown deterministic_text rule: {rule}")

# ---------------------------------------------------------------------------
# deterministic_date evaluator
# ---------------------------------------------------------------------------


def _eval_deterministic_date(
    assertion: Assertion,
    agent_output: dict[str, Any] | None,
    **kwargs: Any,
) -> AssertionResult:
    workspace_state = kwargs.get("workspace_state") or {}
    evidence: list[dict[str, Any]] = []

    current_date_str = workspace_state.get("current_date", "") or workspace_state.get("current_datetime", "")
    if not current_date_str:
        proj = workspace_state.get("project", {})
        if isinstance(proj, dict):
            current_date_str = proj.get("current_date", "")

    current_date = current_date_str[:10] if len(current_date_str) >= 10 else current_date_str
    rule = assertion.rule

    if rule == "current_time_present":
        if not current_date:
            evidence.append({"path": "workspace_state.current_date", "value": None})
            evidence.append({"path": "workspace_state.current_datetime", "value": None})
            return _make_result(
                assertion,
                "failed",
                detail="Workspace current time is missing",
                evidence=evidence,
            )
        if agent_output is None or not isinstance(agent_output, dict):
            return _make_result(assertion, "failed", detail="No agent output to check")
        output_text = str(agent_output)
        if current_date in output_text:
            evidence.append({"path": "agent_output.raw_text", "value": f"contains {current_date}"})
            return _make_result(assertion, "passed", evidence=evidence)
        return _make_result(
            assertion,
            "failed",
            detail=f"Output does not reference current_date {current_date}",
            evidence=evidence,
        )

    if rule == "deadline_not_in_past":
        if agent_output is None or not isinstance(agent_output, dict):
            return _make_result(assertion, "failed", detail="No output to check")
        proj = workspace_state.get("project", {})
        deadline = (proj or {}).get("deadline", "")
        if not deadline:
            return _make_result(assertion, "skipped", detail="No deadline")
        stages = agent_output.get("stages", [])
        if not isinstance(stages, list):
            return _make_result(assertion, "skipped", detail="No stages")
        for idx, stage in enumerate(stages):
            start_date = _date_text(stage.get("start_date", ""))
            end_date = _date_text(stage.get("end_date", ""))
            if current_date and start_date and _date_lt(start_date, current_date):
                evidence.append({
                    "path": f"agent_output.stages[{idx}].start_date",
                    "value": start_date,
                    "current_date": current_date,
                })
                return _make_result(
                    assertion,
                    "failed",
                    detail=(
                        f"Stage '{stage.get('name', f'#{idx}')}' start_date {start_date} "
                        f"is before current_date {current_date}"
                    ),
                    evidence=evidence,
                )
            if current_date and end_date and _date_lt(end_date, current_date):
                evidence.append({
                    "path": f"agent_output.stages[{idx}].end_date",
                    "value": end_date,
                    "current_date": current_date,
                })
                return _make_result(
                    assertion,
                    "failed",
                    detail=(
                        f"Stage '{stage.get('name', f'#{idx}')}' end_date {end_date} "
                        f"is before current_date {current_date}"
                    ),
                    evidence=evidence,
                )
            if end_date and _date_gt(end_date, deadline):
                evidence.append({
                    "path": f"agent_output.stages[{idx}].end_date",
                    "value": end_date,
                    "deadline": deadline,
                })
                return _make_result(
                    assertion,
                    "failed",
                    detail=f"Stage '{stage.get('name', f'#{idx}')}' end {end_date} > deadline {deadline}",
                    evidence=evidence,
                )
        return _make_result(assertion, "passed")

    if rule == "phase_dates_monotonic":
        if agent_output is None or not isinstance(agent_output, dict):
            return _make_result(assertion, "failed", detail="No output to check")
        stages = agent_output.get("stages", [])
        if not isinstance(stages, list) or len(stages) < 2:
            return _make_result(assertion, "skipped", detail="<2 stages")
        prev_end = ""
        for idx, stage in enumerate(stages):
            start = stage.get("start_date", "")
            end = stage.get("end_date", "")
            if start and end and end < start:
                evidence.append({"path": f"agent_output.stages[{idx}]", "value": {"start": start, "end": end}})
                return _make_result(
                    assertion,
                    "failed",
                    detail=f"Stage '{stage.get('name', f'#{idx}')}' end {end} before start {start}",
                    evidence=evidence,
                )
            if start and prev_end and start < prev_end:
                evidence.append({
                    "path": f"agent_output.stages[{idx}].start_date",
                    "value": start,
                    "prev_end": prev_end,
                })
                return _make_result(
                    assertion,
                    "failed",
                    detail=f"Stage '{stage.get('name', f'#{idx}')}' start {start} before prev end {prev_end}",
                    evidence=evidence,
                )
            if end:
                prev_end = end
        return _make_result(assertion, "passed")

    return _make_result(assertion, "skipped", detail=f"Unknown date rule: {rule}")

# ---------------------------------------------------------------------------
# state_path evaluator
# ---------------------------------------------------------------------------


def _eval_state_path(
    assertion: Assertion,
    agent_output: dict[str, Any] | None,
    **kwargs: Any,
) -> AssertionResult:
    workspace_state = kwargs.get("workspace_state") or {}
    evidence: list[dict[str, Any]] = []

    if agent_output is None:
        return _make_result(assertion, "failed", detail="No agent output")

    output_text = str(agent_output)
    rule = assertion.rule

    if rule == "output_reflects_workspace_state":
        paths = assertion.evidence_paths or []
        if not paths:
            return _make_result(assertion, "skipped", detail="No evidence paths configured")

        missing: list[str] = []
        unreflected: list[str] = []
        for path in paths:
            parts = _workspace_path_parts(path)
            if not parts:
                missing.append(path)
                evidence.append({"path": path, "found": False, "reason": "not a workspace_state path"})
                continue
            val = _get_nested(workspace_state, parts)
            if val is None:
                missing.append(path)
                evidence.append({"path": path, "found": False})
                continue
            reflected = _value_reflected_in_text(val, output_text)
            evidence.append({
                "path": path,
                "found": True,
                "reflected": reflected,
                "value": str(val)[:100],
            })
            if not reflected:
                unreflected.append(f"{path}={str(val)[:80]}")

        if missing or unreflected:
            details = []
            if missing:
                details.append(f"Missing evidence paths: {', '.join(missing)}")
            if unreflected:
                details.append(f"Workspace values not reflected in output: {', '.join(unreflected)}")
            return _make_result(
                assertion,
                "failed",
                detail="; ".join(details),
                evidence=evidence,
            )
        return _make_result(assertion, "passed", evidence=evidence)

    if rule == "does_not_invent_members":
        known = set()
        for m in workspace_state.get("members", []):
            name = m.get("display_name", "")
            if name:
                known.add(name)
            uid = m.get("user_id", "")
            if uid:
                known.add(uid)
        project = workspace_state.get("project", {})
        if isinstance(project, dict):
            for key in ("id", "current_stage_id"):
                val = project.get(key)
                if val:
                    known.add(val)
            for collection_name in (
                "stages",
                "tasks",
                "resources",
                "assignment_proposals",
                "assignment_responses",
                "assignment_negotiations",
                "checkin_cycles",
                "checkin_responses",
                "risks",
            ):
                for item in project.get(collection_name, []) or []:
                    if isinstance(item, dict):
                        val = item.get("id")
                        if val:
                            known.add(val)

        fabricated: set[str] = set()

        # 1. Check structured owner fields in proposals, tasks, etc.
        fabricated.update(_check_owner_fields_in_output(agent_output, known, evidence))

        # 2. Check user-N pattern IDs in raw text
        id_pattern = re.compile(r'\b[a-z]+-\d+\b')
        found_ids = set(id_pattern.findall(output_text))
        text_fabricated = found_ids - known
        text_fabricated = {f for f in text_fabricated if not f.startswith("p0") and not f.startswith("p1")}
        if text_fabricated:
            for fid in text_fabricated:
                evidence.append({"path": "agent_output.raw_text", "value": f"fabricated: {fid}"})
            fabricated.update(text_fabricated)

        if fabricated:
            return _make_result(
                assertion,
                "failed",
                detail=f"References entities not in workspace: {', '.join(sorted(fabricated))}",
                evidence=evidence,
            )
        return _make_result(assertion, "passed")

    return _make_result(assertion, "skipped", detail=f"Unknown state_path rule: {rule}")


# ---------------------------------------------------------------------------
# graph evaluator
# ---------------------------------------------------------------------------


def _eval_graph(
    assertion: Assertion,
    agent_output: dict[str, Any] | None,
    **kwargs: Any,
) -> AssertionResult:
    evidence: list[dict[str, Any]] = []

    if agent_output is None or not isinstance(agent_output, dict):
        return _make_result(assertion, "failed", detail="No agent output")

    tasks = agent_output.get("tasks", [])
    if not isinstance(tasks, list):
        return _make_result(assertion, "skipped", detail="No tasks list")

    rule = assertion.rule

    if rule == "dependency_ids_exist":
        all_dep_ids: set[str] = set()
        task_ids: set[str] = set()
        for t in tasks:
            if not isinstance(t, dict):
                continue
            tid = t.get("id", "")
            if tid:
                task_ids.add(tid)
            deps = t.get("dependency_ids", [])
            all_dep_ids.update(deps)
        missing = [d for d in sorted(all_dep_ids) if d and d not in task_ids]
        if missing:
            for mid in missing:
                evidence.append({"path": "agent_output.tasks", "value": f"dep {mid} not found"})
            return _make_result(
                assertion,
                "failed",
                detail=f"Dependency IDs not found: {', '.join(missing)}",
                evidence=evidence,
            )
        return _make_result(assertion, "passed")

    if rule == "dependency_graph_acyclic":
        adj: dict[str, list[str]] = {}
        task_ids_set: set[str] = set()
        for t in tasks:
            if not isinstance(t, dict):
                continue
            tid = t.get("id", "")
            if tid:
                task_ids_set.add(tid)
                deps = t.get("dependency_ids", [])
                adj[tid] = [d for d in deps if d]
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {n: WHITE for n in task_ids_set}
        has_cycle = False
        cycle_path: list[str] = []

        def dfs(node: str, path: list[str]) -> bool:
            nonlocal has_cycle, cycle_path
            color[node] = GRAY
            path.append(node)
            for nb in adj.get(node, []):
                if nb not in color:
                    continue
                if color[nb] == GRAY:
                    has_cycle = True
                    cycle_path = path[path.index(nb):] + [nb]
                    return True
                if color[nb] == BLACK:
                    continue
                if dfs(nb, path):
                    return True
            path.pop()
            color[node] = BLACK
            return False

        for node in task_ids_set:
            if color[node] == WHITE:
                if dfs(node, []):
                    break
        if has_cycle:
            evidence.append({"path": "agent_output.tasks", "value": "cycle detected"})
            return _make_result(
                assertion,
                "failed",
                detail="Dependency graph cycle detected",
                evidence=evidence,
            )
        return _make_result(assertion, "passed")

    if rule == "dependency_not_all_empty_when_ordered":
        ordered_kw = [
            "backend", "frontend", "then", "after", "before",
            "first", "next", "finally",
        ]
        output_text = str(agent_output)
        implies_order = any(k.lower() in output_text.lower() for k in ordered_kw if k)
        if not implies_order:
            # Also check Chinese character patterns
            chinese_order_kw = ["之后", "先", "依赖"]
            for ck in chinese_order_kw:
                if ck in output_text:
                    implies_order = True
                    break
        if not implies_order and "后端" in output_text and "前端" in output_text:
            implies_order = True
        if not implies_order:
            return _make_result(assertion, "passed", detail="No ordering implied")
        all_empty = True
        for t in tasks:
            if not isinstance(t, dict):
                continue
            deps = t.get("dependency_ids", [])
            if deps and any(deps):
                all_empty = False
                break
        if all_empty:
            evidence.append({"path": "agent_output.tasks[*].dependency_ids", "value": "all empty"})
            return _make_result(
                assertion,
                "failed",
                detail="Output implies ordering but all dependency_ids empty",
                evidence=evidence,
            )
        return _make_result(assertion, "passed")

    if rule == "frontend_after_backend_when_api_needed":
        frontend_tasks = []
        backend_tasks = []
        for t in tasks:
            if not isinstance(t, dict):
                continue
            title = (t.get("title", "") or "").lower()
            if any(k in title for k in ["frontend", "page", "ui", "界面"]):
                frontend_tasks.append(t)
            if any(k in title for k in ["backend", "api", "server"]):
                backend_tasks.append(t)
        if not frontend_tasks or not backend_tasks:
            return _make_result(assertion, "passed", detail="No front/backend pair")
        failed = []
        for ft in frontend_tasks:
            ft_title = ft.get("title", "unknown")
            deps = ft.get("dependency_ids", [])
            backend_ids = {bt.get("id", "") for bt in backend_tasks}
            if deps and not set(deps).intersection(backend_ids):
                failed.append(ft_title)
        if failed:
            return _make_result(
                assertion,
                "failed",
                detail=f"Frontend tasks missing backend dep: {', '.join(failed)}",
                evidence=evidence,
            )
        return _make_result(assertion, "passed")

    return _make_result(assertion, "skipped", detail=f"Unknown graph rule: {rule}")


# ---------------------------------------------------------------------------
# diff evaluator
# ---------------------------------------------------------------------------


def _eval_diff(
    assertion: Assertion,
    agent_output: dict[str, Any] | None,
    **kwargs: Any,
) -> AssertionResult:
    evidence: list[dict[str, Any]] = []

    if agent_output is None or not isinstance(agent_output, dict):
        return _make_result(assertion, "failed", detail="No agent output")

    rule = assertion.rule

    if rule == "replan_before_after_nonempty":
        before = agent_output.get("before")
        after = agent_output.get("after")
        missing = []
        if not before:
            missing.append("before")
        if not after:
            missing.append("after")
        if missing:
            evidence.append({"path": "agent_output", "value": f"missing: {', '.join(missing)}"})
            return _make_result(
                assertion, "failed",
                detail=f"Missing before/after: {', '.join(missing)}",
                evidence=evidence,
            )
        return _make_result(assertion, "passed")

    if rule == "replan_changes_under_high_risk":
        before = agent_output.get("before")
        after = agent_output.get("after")
        if not before or not after:
            return _make_result(assertion, "skipped", detail="Missing before/after")

        # Check for meaningful structural changes: if before and after have same
        # task ids but only differ in notes/reasons, it's a no-op.
        meaningful = _replan_has_meaningful_change(before, after, agent_output)
        if not meaningful:
            before_str = str(before)
            after_str = str(after)
            evidence.append({"path": "agent_output.before", "value": before_str[:200]})
            evidence.append({"path": "agent_output.after", "value": after_str[:200]})
            evidence.append({
                "path": "agent_output.changes",
                "value": agent_output.get("changes", []),
            })
            return _make_result(
                assertion, "failed",
                detail="No meaningful change between before and after (only notes/reasons differ)",
                evidence=evidence,
            )
        return _make_result(assertion, "passed", evidence=evidence)

    return _make_result(assertion, "skipped", detail=f"Unknown diff rule: {rule}")


# ---------------------------------------------------------------------------
# trace evaluator
# ---------------------------------------------------------------------------


def _eval_trace(
    assertion: Assertion,
    agent_output: dict[str, Any] | None,
    **kwargs: Any,
) -> AssertionResult:
    agent_status = kwargs.get("agent_status", "")
    evidence: list[dict[str, Any]] = []

    rule = assertion.rule

    if rule == "correct_module_chosen":
        expected = assertion.expected or []
        if expected:
            ep = kwargs.get("entrypoint", "")
            if ep in expected:
                evidence.append({"path": "entrypoint", "value": ep})
                return _make_result(assertion, "passed", evidence=evidence)
            evidence.append({"path": "entrypoint", "value": ep, "expected": expected})
            return _make_result(
                assertion, "failed",
                detail=f"Entrypoint '{ep}' not in expected: {expected}",
                evidence=evidence,
            )
        return _make_result(assertion, "passed")

    if rule == "fallback_evidence_present":
        if agent_status in ("fallback", "repaired"):
            output_text = str(agent_output) if agent_output else ""
            has_fallback_ref = any(
                kw in output_text.lower()
                for kw in ["fallback", "保守", "异常", "备用", "retry", "重试", "repair", "修复"]
            )
            if agent_output and has_fallback_ref:
                evidence.append({"path": "agent_status", "value": agent_status})
                return _make_result(assertion, "passed", evidence=evidence)
            if agent_output:
                evidence.append({"path": "agent_output.raw_text", "value": "missing fallback/recovery label"})
                return _make_result(
                    assertion,
                    "failed",
                    detail="Fallback output is non-empty but lacks transparent fallback/recovery label",
                    evidence=evidence,
                )
            return _make_result(
                assertion, "failed",
                detail="Fallback used but output lacks recovery evidence",
                evidence=evidence,
            )
        return _make_result(assertion, "passed", detail="No fallback needed")

    return _make_result(assertion, "skipped", detail=f"Unknown trace rule: {rule}")


# ---------------------------------------------------------------------------
# llm_semantic evaluator (placeholder)
# ---------------------------------------------------------------------------


def _eval_llm_semantic(
    assertion: Assertion,
    agent_output: dict[str, Any] | None,
    **kwargs: Any,
) -> AssertionResult:
    return _make_result(
        assertion, "skipped",
        detail="LLM semantic evaluator is not implemented in deterministic assertion engine",
    )


# ---------------------------------------------------------------------------
# Default assertion packs for v1-compatible fixtures
# ---------------------------------------------------------------------------


ENTRYPOINT_TO_EVENT_TYPE = {
    "clarify": "clarify",
    "plan": "plan",
    "breakdown": "breakdown",
    "recommend-assignments": "assign",
    "negotiate": "negotiate",
    "active-push": "push",
    "analyze-risk": "risk",
    "replan": "replan",
}


CHINESE_OWNER_STOPWORDS = {
    "后端",
    "前端",
    "测试",
    "设计",
    "产品",
    "队长",
    "成员",
    "同学",
    "团队",
}


COMMON_CHINESE_SURNAME_CHARS = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟"
    "平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋庞熊纪舒屈项"
    "祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡"
)


COMMON_CHINESE_COMPOUND_SURNAMES = (
    "欧阳",
    "太史",
    "端木",
    "上官",
    "司马",
    "东方",
    "独孤",
    "南宫",
    "万俟",
    "闻人",
    "夏侯",
    "诸葛",
    "尉迟",
    "公羊",
    "赫连",
    "澹台",
    "皇甫",
    "宗政",
    "濮阳",
    "公冶",
    "太叔",
    "申屠",
    "公孙",
    "慕容",
    "仲孙",
    "钟离",
    "长孙",
    "宇文",
    "司徒",
    "鲜于",
    "司空",
    "闾丘",
    "子车",
    "亓官",
    "司寇",
    "巫马",
    "公西",
    "颛孙",
    "壤驷",
    "公良",
    "漆雕",
    "乐正",
    "宰父",
    "谷梁",
    "拓跋",
    "夹谷",
    "轩辕",
    "令狐",
    "段干",
    "百里",
    "东郭",
    "南门",
    "呼延",
    "羊舌",
    "微生",
    "公户",
    "公玉",
    "公仪",
    "梁丘",
    "公仲",
    "公上",
    "公门",
    "公山",
    "公坚",
    "左丘",
    "公伯",
    "西门",
    "公祖",
    "第五",
    "公乘",
    "贯丘",
    "公皙",
    "南荣",
    "东里",
    "东宫",
    "仲长",
    "子书",
    "子桑",
    "即墨",
    "达奚",
    "褚师",
)


CHINESE_NAME_BAD_SUFFIXES = {
    "前",
    "后",
    "中",
    "可",
    "的",
    "了",
    "为",
    "与",
    "和",
    "或",
    "及",
    "在",
    "需",
    "要",
    "应",
    "能",
    "将",
    "把",
    "以",
    "按",
    "先",
    "再",
    "等",
    "上",
    "下",
    "时",
}


NEGATED_SCOPE_MARKERS = (
    "不涉及",
    "不接入",
    "不支持",
    "不包含",
    "不开发",
    "不实现",
    "不做",
    "不用",
    "无需",
    "不需要",
    "不纳入",
    "不考虑",
    "不会",
    "暂不",
    "先不",
    "避免",
    "排除",
    "仅限web",
    "仅限Web",
)


NON_COMMITTAL_SCOPE_PATHS = {
    "out_of_scope",
    "defer",
    "suggested_questions",
    "unknowns",
    "decision_points",
    "risks",
    "source_summary",
}


DEFAULT_SCOPE_FORBIDDEN = [
    "GitHub",
    "飞书",
    "Feishu",
    "教务系统",
    "第三方登录",
    "移动端 App",
    "原生 App",
    "iOS App",
    "Android App",
    "Electron",
    "桌面客户端",
    "桌面端客户端",
    "日历集成",
]


def build_default_assertions_for_case(
    *,
    case_id: str,
    module: str,
    entrypoint: str,
) -> list[Assertion]:
    """Build a pragmatic v2 assertion pack for legacy v1 fixtures.

    Explicit fixture assertions always win. This default pack keeps old fixtures
    executable while making every seed case participate in assertion reporting.
    """

    def aid(suffix: str) -> str:
        return f"{case_id}_{suffix}"

    assertions = [
        Assertion(
            id=aid("valid_schema"),
            group="output_contract",
            severity="hard",
            evaluator="schema",
            rule="valid_json_contract",
            failure_category="schema_failure",
        ),
        Assertion(
            id=aid("correct_module"),
            group="trace",
            severity="hard",
            evaluator="trace",
            rule="correct_module_chosen",
            expected=[entrypoint],
            failure_category="wrong_module_behavior",
        ),
        Assertion(
            id=aid("no_external_scope"),
            group="mvp_boundary",
            severity="hard",
            evaluator="deterministic_text",
            rule="forbidden_terms_absent",
            forbidden=DEFAULT_SCOPE_FORBIDDEN,
            failure_category="scope_creep",
        ),
    ]

    if module in {"clarification", "planning", "breakdown", "assignment", "replan"}:
        assertions.append(
            Assertion(
                id=aid("proposal_shape"),
                group="output_contract",
                severity="hard",
                evaluator="schema",
                rule="proposal_shape_valid",
                failure_category="persistence_boundary_violation",
            )
        )

    if module == "clarification":
        assertions.extend([
            Assertion(
                id=aid("current_time_present"),
                group="temporal_correctness",
                severity="major",
                evaluator="deterministic_date",
                rule="current_time_present",
                failure_category="date_time_error",
            ),
            Assertion(
                id=aid("unknowns_and_assumptions"),
                group="state_grounding",
                severity="major",
                evaluator="deterministic_text",
                rule="required_terms_present",
                required=["unknowns", "assumptions"],
                failure_category="context_missing",
            ),
            Assertion(
                id=aid("questions_and_decisions"),
                group="actionability",
                severity="major",
                evaluator="deterministic_text",
                rule="required_terms_present",
                required=["suggested_questions", "decision_points"],
                failure_category="weak_actionability",
            ),
        ])
    elif module == "planning":
        assertions.extend([
            Assertion(
                id=aid("current_time_present"),
                group="temporal_correctness",
                severity="hard",
                evaluator="deterministic_date",
                rule="current_time_present",
                failure_category="date_time_error",
            ),
            Assertion(
                id=aid("deadline_not_in_past"),
                group="temporal_correctness",
                severity="hard",
                evaluator="deterministic_date",
                rule="deadline_not_in_past",
                failure_category="date_time_error",
            ),
            Assertion(
                id=aid("phase_dates_monotonic"),
                group="temporal_correctness",
                severity="major",
                evaluator="deterministic_date",
                rule="phase_dates_monotonic",
                failure_category="date_time_error",
            ),
            Assertion(
                id=aid("stages_nonempty"),
                group="output_contract",
                severity="hard",
                evaluator="schema",
                rule="no_empty_required_sections",
                required=["stages"],
                failure_category="schema_failure",
            ),
        ])
    elif module == "breakdown":
        assertions.extend([
            Assertion(
                id=aid("tasks_nonempty"),
                group="output_contract",
                severity="hard",
                evaluator="schema",
                rule="no_empty_required_sections",
                required=["tasks"],
                failure_category="schema_failure",
            ),
            Assertion(
                id=aid("dependency_ids_exist"),
                group="workflow_consistency",
                severity="hard",
                evaluator="graph",
                rule="dependency_ids_exist",
                failure_category="dependency_inconsistency",
            ),
            Assertion(
                id=aid("dependency_graph_acyclic"),
                group="workflow_consistency",
                severity="hard",
                evaluator="graph",
                rule="dependency_graph_acyclic",
                failure_category="dependency_inconsistency",
            ),
            Assertion(
                id=aid("dependencies_not_empty_when_ordered"),
                group="workflow_consistency",
                severity="hard",
                evaluator="graph",
                rule="dependency_not_all_empty_when_ordered",
                failure_category="dependency_inconsistency",
            ),
            Assertion(
                id=aid("acceptance_criteria_nonempty"),
                group="output_contract",
                severity="major",
                evaluator="schema",
                rule="structured_fields_nonempty",
                required=["tasks[*].acceptance_criteria"],
                failure_category="weak_actionability",
            ),
        ])
    elif module == "assignment":
        assertions.extend([
            Assertion(
                id=aid("assignments_nonempty"),
                group="output_contract",
                severity="hard",
                evaluator="schema",
                rule="no_empty_required_sections",
                required=["assignments"],
                failure_category="schema_failure",
            ),
            Assertion(
                id=aid("does_not_invent_members"),
                group="state_grounding",
                severity="hard",
                evaluator="state_path",
                rule="does_not_invent_members",
                failure_category="hallucinated_entity",
            ),
            Assertion(
                id=aid("proposal_owners_nonempty"),
                group="output_contract",
                severity="hard",
                evaluator="schema",
                rule="structured_fields_nonempty",
                required=["assignments[*].recommended_owner_user_id"],
                failure_category="weak_actionability",
            ),
        ])
    elif module == "negotiate":
        assertions.extend([
            Assertion(
                id=aid("message_and_options_present"),
                group="actionability",
                severity="major",
                evaluator="schema",
                rule="structured_fields_nonempty",
                required=["message", "options"],
                failure_category="weak_actionability",
            ),
            Assertion(
                id=aid("does_not_invent_members"),
                group="state_grounding",
                severity="hard",
                evaluator="state_path",
                rule="does_not_invent_members",
                failure_category="hallucinated_entity",
            ),
        ])
    elif module == "active_push":
        assertions.extend([
            Assertion(
                id=aid("action_cards_nonempty"),
                group="output_contract",
                severity="hard",
                evaluator="schema",
                rule="no_empty_required_sections",
                required=["action_cards"],
                failure_category="schema_failure",
            ),
            Assertion(
                id=aid("card_fields_nonempty"),
                group="actionability",
                severity="hard",
                evaluator="schema",
                rule="structured_fields_nonempty",
                required=[
                    "action_cards[*].title",
                    "action_cards[*].content",
                    "action_cards[*].start_suggestion",
                    "action_cards[*].completion_standard",
                ],
                failure_category="weak_actionability",
            ),
        ])
    elif module == "risk":
        assertions.extend([
            Assertion(
                id=aid("risks_nonempty"),
                group="output_contract",
                severity="hard",
                evaluator="schema",
                rule="no_empty_required_sections",
                required=["risks"],
                failure_category="schema_failure",
            ),
            Assertion(
                id=aid("risk_evidence_and_mitigation"),
                group="actionability",
                severity="major",
                evaluator="schema",
                rule="structured_fields_nonempty",
                required=["risks[*].evidence", "risks[*].recommendation"],
                failure_category="weak_actionability",
            ),
        ])
    elif module == "replan":
        assertions.extend([
            Assertion(
                id=aid("before_after_nonempty"),
                group="replanning_effectiveness",
                severity="hard",
                evaluator="diff",
                rule="replan_before_after_nonempty",
                failure_category="no_op_replan",
            ),
            Assertion(
                id=aid("changes_under_high_risk"),
                group="replanning_effectiveness",
                severity="hard",
                evaluator="diff",
                rule="replan_changes_under_high_risk",
                failure_category="no_op_replan",
            ),
            Assertion(
                id=aid("impact_and_changes_present"),
                group="actionability",
                severity="major",
                evaluator="deterministic_text",
                rule="required_terms_present",
                required=["impact"],
                failure_category="weak_actionability",
            ),
        ])
    elif module == "reliability":
        assertions.append(
            Assertion(
                id=aid("fallback_evidence_present"),
                group="reliability",
                severity="hard",
                evaluator="trace",
                rule="fallback_evidence_present",
                failure_category="fallback_quality_failure",
            )
        )

    return assertions


# ---------------------------------------------------------------------------
# Batch evaluation
# ---------------------------------------------------------------------------


def run_all_assertions(
    assertions: list[Assertion],
    agent_output: dict[str, Any] | None,
    *,
    agent_status: str = "",
    workspace_state: dict[str, Any] | None = None,
    raw_agent_output: str | None = None,
    timeline: list[dict[str, Any]] | None = None,
    entrypoint: str = "",
) -> list[AssertionResult]:
    results: list[AssertionResult] = []
    for assertion in assertions:
        result = evaluate_assertion(
            assertion,
            agent_output,
            agent_status=agent_status,
            workspace_state=workspace_state,
            raw_agent_output=raw_agent_output,
            timeline=timeline,
            entrypoint=entrypoint,
        )
        results.append(result)
    return results


def compute_assertion_metrics(
    results: list[AssertionResult],
) -> dict[str, Any]:
    hard_fail_count = sum(
        1 for r in results
        if r.status == "failed" and r.severity.value == "hard"
    )
    total_penalty = sum(r.score_delta for r in results if r.status == "failed")
    # Hard assertion failure forces weighted_score to 0.0 regardless of other scores
    if hard_fail_count > 0:
        weighted_score = 0.0
    else:
        weighted_score = max(0.0, min(1.0, 1.0 + total_penalty / 100.0))
    failed_ids = [r.assertion_id for r in results if r.status == "failed"]
    failure_cats = list({
        r.failure_category for r in results
        if r.status == "failed" and r.failure_category
    })

    return {
        "hard_fail_count": hard_fail_count,
        "weighted_score": round(weighted_score, 4),
        "failed_assertion_ids": failed_ids,
        "failure_categories": failure_cats,
        "total_assertions": len(results),
        "passed_count": sum(1 for r in results if r.status == "passed"),
        "failed_count": sum(1 for r in results if r.status == "failed"),
        "skipped_count": sum(1 for r in results if r.status == "skipped"),
    }


def _get_nested(d: dict[str, Any], path: list[str]) -> Any:
    current: Any = d
    for key in path:
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list) and key.isdigit():
            idx = int(key)
            current = current[idx] if 0 <= idx < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def _check_structured_path_nonempty(
    output: dict[str, Any] | None,
    structured_path: str,
) -> tuple[bool, str]:
    """Check that a structured path like cards[*].next_action is non-empty.

    Returns (True, "") on success, (False, description) on failure.
    Supports [*] to iterate over all items in a list at that level.
    """
    if output is None or not isinstance(output, dict):
        return False, "no agent output"

    parts = structured_path.split(".")
    current: Any = output

    for i, part in enumerate(parts):
        if "[*]" in part:
            field_name = part.replace("[*]", "")
            if not isinstance(current, dict) or field_name not in current:
                return False, f"missing '{field_name}'"
            items = current[field_name]
            if not isinstance(items, list):
                return False, f"'{field_name}' not a list"
            if not items:
                return False, f"empty list '{field_name}'"
            remaining = ".".join(parts[i + 1:])
            if not remaining:
                # Just check list non-empty - already done above
                return True, ""
            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    return False, f"item in '{field_name}' not a dict"
                val = _get_nested(item, remaining.split("."))
                if val is None:
                    return False, f"missing '{remaining}' in {field_name}[{idx}]"
                if isinstance(val, str) and not val.strip():
                    return False, f"empty '{remaining}' in {field_name}[{idx}]"
                if isinstance(val, list) and not val:
                    return False, f"empty list '{remaining}' in {field_name}[{idx}]"
            return True, ""
        else:
            if not isinstance(current, dict):
                return False, f"cannot navigate '{part}'"
            current = current.get(part)
            if current is None:
                return False, f"missing '{part}'"
    # Leaf reached; check non-empty
    if isinstance(current, str) and not current.strip():
        return False, f"empty leaf '{structured_path}'"
    if isinstance(current, list) and not current:
        return False, f"empty list leaf '{structured_path}'"
    return True, ""


def _check_owner_fields_in_output(
    agent_output: dict[str, Any],
    known: set[str],
    evidence: list[dict[str, Any]],
) -> set[str]:
    """Check structured owner fields in output against known members.

    Walks proposals, tasks, and cards to find recommended_owner,
    backup_owner, owner_user_id, backup_owner_user_id fields and checks
    each value against the known set.
    """
    fabricated: set[str] = set()

    if not agent_output or not isinstance(agent_output, dict):
        return fabricated

    # Proposals
    for prop in agent_output.get("proposals", []):
        if not isinstance(prop, dict):
            continue
        for field in ("recommended_owner", "backup_owner"):
            val = prop.get(field)
            if val and isinstance(val, str) and val not in known:
                fabricated.add(val)
                evidence.append({"path": f"proposals[*].{field}", "value": val})

    # Current assignment recommendation schema
    for assignment in agent_output.get("assignments", []):
        if not isinstance(assignment, dict):
            continue
        for field in ("recommended_owner_user_id", "backup_owner_user_id"):
            val = assignment.get(field)
            if val and isinstance(val, str) and val not in known:
                fabricated.add(val)
                evidence.append({"path": f"assignments[*].{field}", "value": val})

    # Tasks
    for task in agent_output.get("tasks", []):
        if not isinstance(task, dict):
            continue
        for field in ("owner_user_id", "backup_owner_user_id"):
            val = task.get(field)
            if val and isinstance(val, str) and val not in known:
                fabricated.add(val)
                evidence.append({"path": f"tasks[*].{field}", "value": val})

    # Cards (active push)
    for card in agent_output.get("cards", []):
        if not isinstance(card, dict):
            continue
        val = card.get("member")
        if val and isinstance(val, str) and val not in known:
            fabricated.add(val)
            evidence.append({"path": "cards[*].member", "value": val})

    for card in agent_output.get("action_cards", []):
        if not isinstance(card, dict):
            continue
        val = card.get("user_id")
        if val and isinstance(val, str) and val not in known:
            fabricated.add(val)
            evidence.append({"path": "action_cards[*].user_id", "value": val})

    for field in ("from_user_id", "current_owner_user_id"):
        val = agent_output.get(field)
        if val and isinstance(val, str) and val not in known:
            fabricated.add(val)
            evidence.append({"path": f"agent_output.{field}", "value": val})

    return fabricated


def _forbidden_term_has_unnegated_occurrence(term: str, text: str) -> bool:
    """Return True when a forbidden term appears as an included scope.

    Boundary assertions should flag "接入教务系统", but not "暂不接入教务系统".
    This is intentionally deterministic and local-window based; deeper semantic
    calls belong to the judge, not the hard assertion gate.
    """
    if not term:
        return False

    text_lower = text.lower()
    term_lower = term.lower()
    start = 0
    while True:
        idx = text_lower.find(term_lower, start)
        if idx < 0:
            return False
        if not _scope_occurrence_is_negated(text, idx, len(term)):
            return True
        start = idx + max(len(term_lower), 1)


def _find_unnegated_forbidden_terms(
    value: Any,
    forbidden: list[str],
    path: str = "agent_output",
) -> list[tuple[str, str]]:
    if _path_is_non_committal_scope_context(path):
        return []
    if isinstance(value, dict):
        findings: list[tuple[str, str]] = []
        for key, child in value.items():
            findings.extend(_find_unnegated_forbidden_terms(child, forbidden, f"{path}.{key}"))
        return findings
    if isinstance(value, list):
        findings = []
        for idx, child in enumerate(value):
            findings.extend(_find_unnegated_forbidden_terms(child, forbidden, f"{path}[{idx}]"))
        return findings
    if isinstance(value, str):
        return [
            (term, path)
            for term in forbidden
            if _forbidden_term_has_unnegated_occurrence(term, value)
        ]
    return []


def _path_is_non_committal_scope_context(path: str) -> bool:
    normalized = path.replace("[", ".").replace("]", "")
    parts = {part for part in normalized.split(".") if part and not part.isdigit()}
    return bool(parts.intersection(NON_COMMITTAL_SCOPE_PATHS))


def _scope_occurrence_is_negated(text: str, term_start: int, term_len: int) -> bool:
    before = text[max(0, term_start - 28):term_start]
    after = text[term_start + term_len:term_start + term_len + 8]
    before_compact = re.sub(r"\s+", "", before).lower()
    after_compact = re.sub(r"\s+", "", after).lower()

    if any(marker.lower() in before_compact for marker in NEGATED_SCOPE_MARKERS):
        return True
    return any(marker.lower() in after_compact for marker in ("不做", "不用", "不支持", "不需要", "暂不"))


def _extract_chinese_owner_candidates(output_text: str) -> set[str]:
    action_words = "负责|完成|承担|处理|跟进|接手|主导|协助"
    compound_surname_pattern = "|".join(COMMON_CHINESE_COMPOUND_SURNAMES)
    name_pattern = (
        rf"(?:[小老][{COMMON_CHINESE_SURNAME_CHARS}]|"
        rf"(?:{compound_surname_pattern})[\u4e00-\u9fff]{{1,2}}|"
        rf"[{COMMON_CHINESE_SURNAME_CHARS}][\u4e00-\u9fff]{{1,2}})"
    )
    candidates: set[str] = set()

    trigger_re = re.compile(
        rf"(?:建议由|建议让|建议安排|建议指派|由|推荐|让|找|分配|指派|安排|交给)"
        rf"[：:\s]*({name_pattern})(?={action_words}|[，,。；;\s]|$)"
    )
    direct_re = re.compile(
        rf"(?<![\u4e00-\u9fff])({name_pattern})(?={action_words})"
    )

    for pattern in (trigger_re, direct_re):
        for match in pattern.finditer(output_text):
            candidate = match.group(1)
            if _looks_like_chinese_person_name(candidate):
                candidates.add(candidate)
    return candidates


def _looks_like_chinese_person_name(candidate: str) -> bool:
    if not candidate or candidate in CHINESE_OWNER_STOPWORDS:
        return False
    if len(candidate) < 2 or len(candidate) > 3:
        return False
    if candidate[-1] in CHINESE_NAME_BAD_SUFFIXES:
        return False
    if candidate.startswith(("小", "老")):
        return len(candidate) == 2 and candidate[1] in COMMON_CHINESE_SURNAME_CHARS
    if any(candidate.startswith(surname) for surname in COMMON_CHINESE_COMPOUND_SURNAMES):
        surname = next(
            surname for surname in COMMON_CHINESE_COMPOUND_SURNAMES
            if candidate.startswith(surname)
        )
        given_name_len = len(candidate) - len(surname)
        return given_name_len in {1, 2}
    return candidate[0] in COMMON_CHINESE_SURNAME_CHARS


# ---------------------------------------------------------------------------
# Replan meaningful change detection
# ---------------------------------------------------------------------------

MEANINGFUL_CHANGE_FIELDS = frozenset({
    "due_date", "start_date", "end_date", "status", "owner_user_id",
    "owner", "priority", "can_cut", "scope", "deadline",
})


def _replan_has_meaningful_change(
    before: Any,
    after: Any,
    output: dict[str, Any],
) -> bool:
    """Check if a replan has meaningful change beyond note/reason fields."""
    for key in ("task_changes", "stage_adjustments"):
        value = output.get(key)
        if isinstance(value, list) and value:
            return True

    # 1. Check explicit non-empty changes list
    after_obj = output.get("after")
    if isinstance(after_obj, str):
        after_obj = {}
    elif not isinstance(after_obj, dict):
        after_obj = {}
    changes = output.get("changes") or after_obj.get("changes", [])
    if changes and isinstance(changes, list) and len(changes) > 0:
        if any(isinstance(c, str) and len(c) > 5 for c in changes):
            return True
        if any(isinstance(c, dict) and c.get("action") for c in changes):
            return True

    # 2. Check structured content for meaningful diffs
    for key in ("tasks", "stages"):
        before_items = _ensure_list(before.get(key, []) if isinstance(before, dict) else [])
        after_items = _ensure_list(after.get(key, []) if isinstance(after, dict) else [])
        before_map = {item.get("id", ""): item for item in before_items if item.get("id")}
        after_map = {item.get("id", ""): item for item in after_items if item.get("id")}
        all_ids = set(before_map.keys()) | set(after_map.keys())
        for item_id in all_ids:
            b_item = before_map.get(item_id, {})
            a_item = after_map.get(item_id, {})
            for field in MEANINGFUL_CHANGE_FIELDS:
                b_val = b_item.get(field)
                a_val = a_item.get(field)
                if b_val != a_val:
                    return True
        new_ids = set(after_map.keys()) - set(before_map.keys())
        removed_ids = set(before_map.keys()) - set(after_map.keys())
        if new_ids or removed_ids:
            return True

    # 3. Check top-level meaningful fields
    if isinstance(before, dict) and isinstance(after, dict):
        for field in ("scope", "deadline", "status", "priority"):
            if before.get(field) != after.get(field):
                return True

    return False


def _ensure_list(value: Any) -> list:
    """Safely convert value to list."""
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _event_type_for_assertion(assertion: Assertion, entrypoint: str) -> str:
    payload_event = (assertion.payload or {}).get("event_type")
    if isinstance(payload_event, str) and payload_event:
        return ENTRYPOINT_TO_EVENT_TYPE.get(payload_event, payload_event)
    return ENTRYPOINT_TO_EVENT_TYPE.get(entrypoint, entrypoint)


def _date_text(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value[:10]
    return ""


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def _date_lt(left: str, right: str) -> bool:
    left_date = _parse_date(left)
    right_date = _parse_date(right)
    if left_date and right_date:
        return left_date < right_date
    return left < right


def _date_gt(left: str, right: str) -> bool:
    left_date = _parse_date(left)
    right_date = _parse_date(right)
    if left_date and right_date:
        return left_date > right_date
    return left > right


def _workspace_path_parts(path: str) -> list[str]:
    if path.startswith("workspace_state."):
        return path.removeprefix("workspace_state.").split(".")
    if path.startswith("workspace."):
        return path.removeprefix("workspace.").split(".")
    return []


def _value_reflected_in_text(value: Any, output_text: str) -> bool:
    if isinstance(value, dict):
        scalars = list(_iter_scalar_values(value))
        return bool(scalars) and any(_value_reflected_in_text(v, output_text) for v in scalars)
    if isinstance(value, list):
        scalars = list(_iter_scalar_values(value))
        return bool(scalars) and any(_value_reflected_in_text(v, output_text) for v in scalars)

    text = str(value).strip()
    if not text:
        return True
    return text.lower() in output_text.lower()


def _iter_scalar_values(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_scalar_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_scalar_values(item)
    elif value is not None:
        yield value
