# -*- coding: utf-8 -*-
"""Deterministic candidate extraction and semantic guard orchestration for AgentEval v2.1."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

from app.agent.llm_client import LLMClient
from app.agent_eval.schemas import (
    SemanticCandidate, SemanticCandidateDecision,
    SemanticCandidateSource, SemanticDecision,
    SemanticFinding, SemanticGuardMode, SemanticGuardReport,
    SemanticJudgeDiagnostic, SemanticJudgeDiagnosticKind,
    SemanticRisk, ScopeCommitmentLevel, FailureCategory,
)
from app.agent_eval.semantic_judge import (
    SemanticJudgeRequest, run_semantic_judge,
)
from app.agent_eval.entity_resolver import (
    EntityResolution,
    build_workspace_entity_index,
    resolve_workspace_entity,
)

DEFAULT_SCOPE_CONTRACT = {
    "allowed": ["Web MVP", "project direction clarification", "stage planning",
        "task breakdown", "assignment recommendation", "assignment negotiation",
        "active push", "check-in analysis", "risk analysis", "replanning proposal",
        "manual confirmation before high-impact changes"],
    "disallowed": ["native desktop app", "mobile app", "third-party login",
        "external system integration", "automatic academic system integration",
        "GitHub integration", "Lark or Feishu integration",
        "cloud deployment as a required MVP deliverable"],
    "ambiguous_terms": ["移动端", "桌面端", "外部系统", "自动同步", "教务系统"],
}
_ID_RE = re.compile(r"\b(?:user|task|stage|prop)-[A-Za-z0-9_-]+\b")
_RAW_EXCERPT_LEN = 200
_ACTION_WORDS = "负责|完成|承担|处理|跟进|接手|主导|协助"
_ENTITY_TRIGGER_RE = re.compile(
    r"(?:建议由|建议让|建议安排|建议指派|由|推荐|让|找|分配|指派|安排|交给)"
    r"[：:\s]*([一-鿿]{2,3})(?=" + _ACTION_WORDS + r"|[，,。；;\s/]|$)"
)
_DIRECT_OWNER_RE = re.compile(
    r"(?<![一-鿿])([一-鿿]{2,3})(?=" + _ACTION_WORDS + r")"
)
_TIME_SLASH_RE = re.compile(
    r"(?:\d+|[一二三四五六七八九十]+)\s*(?:小时|天)?[／/]([一-鿿]{2,3})(?=完成|交付|做完|内|$)"
)

def extract_entity_candidates(
    agent_output: dict[str, Any] | None,
    workspace_state: dict[str, Any],
) -> list[SemanticCandidate]:
    if not isinstance(agent_output, dict):
        return []
    known = _known_workspace_tokens(workspace_state)
    known.update(_output_defined_ids(agent_output))
    candidates: list[SemanticCandidate] = []
    for path, value in _walk(agent_output):
        if isinstance(value, str):
            for match in _ID_RE.finditer(value):
                span = match.group(0)
                if span in known:
                    continue
                candidates.append(SemanticCandidate(
                    kind="entity", span=span, path=path,
                    local_context=_local_context(value, match.start(), match.end()),
                    deterministic_decision=SemanticCandidateDecision.fail,
                    source=SemanticCandidateSource.id_pattern, risk=SemanticRisk.high,
                    reason="ID reference absent from WorkspaceState.",
                ))
            for match in _ENTITY_TRIGGER_RE.finditer(value):
                span = match.group(1)
                if (
                    span in known
                    or not _looks_like_person_name(span)
                    or _looks_like_time_or_range_context(value, match.start(1), match.end(1))
                ):
                    continue
                candidates.append(SemanticCandidate(
                    kind="entity", span=span, path=path,
                    local_context=_local_context(value, match.start(1), match.end(1)),
                    deterministic_decision=SemanticCandidateDecision.ambiguous,
                    source=SemanticCandidateSource.text_trigger, risk=SemanticRisk.high,
                    reason="Chinese span in owner context needs semantic judgement.",
                ))
            for match in _DIRECT_OWNER_RE.finditer(value):
                span = match.group(1)
                if (
                    span in known
                    or not _looks_like_person_name(span)
                    or _looks_like_time_or_range_context(value, match.start(1), match.end(1))
                ):
                    continue
                candidates.append(SemanticCandidate(
                    kind="entity", span=span, path=path,
                    local_context=_local_context(value, match.start(1), match.end(1)),
                    deterministic_decision=SemanticCandidateDecision.ambiguous,
                    source=SemanticCandidateSource.text_trigger, risk=SemanticRisk.high,
                    reason="Chinese span near action verb, needs semantic judgement.",
                ))
            for match in _TIME_SLASH_RE.finditer(value):
                span = match.group(1)
                candidates.append(SemanticCandidate(
                    kind="entity", span=span, path=path,
                    local_context=_local_context(value, match.start(1), match.end(1)),
                    deterministic_decision=SemanticCandidateDecision.pass_,
                    source=SemanticCandidateSource.time_or_range_pattern,
                    risk=SemanticRisk.low, reason="Time/range expression, not a person.",
                ))
    for field in ("owner_user_id", "backup_owner_user_id", "recommended_owner_user_id",
                  "current_owner_user_id", "from_user_id"):
        for fpath, fvalue in _find_key(agent_output, field):
            if isinstance(fvalue, str) and fvalue and fvalue not in known:
                candidates.append(SemanticCandidate(
                    kind="entity", span=fvalue, path=fpath, local_context=fvalue,
                    deterministic_decision=SemanticCandidateDecision.fail,
                    source=SemanticCandidateSource.structured_field,
                    risk=SemanticRisk.high,
                    reason=f"Structured field {field} references unknown entity.",
                ))
    return _dedupe_candidates(candidates)


def extract_scope_candidates(
    agent_output: dict[str, Any] | None,
    scope_contract: dict[str, list[str]] | None = None,
) -> list[SemanticCandidate]:
    if not isinstance(agent_output, dict):
        return []

    contract = scope_contract or DEFAULT_SCOPE_CONTRACT
    candidates: list[SemanticCandidate] = []
    deterministic_fail_terms = {
        "electron": "Native desktop app commitment.",
        "docker": "Deployment platform commitment.",
        "移动端 app": "Mobile app commitment.",
        "ios": "Mobile app commitment.",
        "android": "Mobile app commitment.",
        "教务系统课表对接": "Academic system integration commitment.",
        "教务系统对接": "Academic system integration commitment.",
        "github 集成": "External integration commitment.",
        "集成 github": "External integration commitment.",
        "飞书集成": "External integration commitment.",
        "集成飞书": "External integration commitment.",
        "lark 集成": "External integration commitment.",
        "集成 lark": "External integration commitment.",
    }
    ambiguous_terms = contract.get("ambiguous_terms", [])

    for path, value in _walk(agent_output):
        if not isinstance(value, str):
            continue
        compact = re.sub(r"\s+", "", value).lower()
        if _path_is_non_committal(path) or _is_future_direction(value):
            continue
        if "手动导入" in value and "教务系统" in value and "csv" in compact:
            continue

        for term, reason in deterministic_fail_terms.items():
            if term.lower().replace(" ", "") in compact:
                candidates.append(
                    SemanticCandidate(
                        kind="scope",
                        span=term,
                        path=path,
                        local_context=value,
                        deterministic_decision=SemanticCandidateDecision.fail,
                        source=SemanticCandidateSource.scope_keyword,
                        commitment_level=ScopeCommitmentLevel.implementation_commitment,
                        reason=reason,
                    )
                )

        if "桌面端主流浏览器" in value or (
            "桌面端" in value and _looks_like_web_compatibility_context(value)
        ):
            candidates.append(
                SemanticCandidate(
                    kind="scope",
                    span="桌面端主流浏览器" if "桌面端主流浏览器" in value else "桌面端",
                    path=path,
                    local_context=value,
                    deterministic_decision=SemanticCandidateDecision.pass_,
                    source=SemanticCandidateSource.ambiguous_term,
                    commitment_level=ScopeCommitmentLevel.compatibility_note,
                    reason="Desktop browser wording is Web compatibility, not native desktop app scope.",
                )
            )
            continue

        for term in ambiguous_terms:
            if term and term.lower() in compact:
                candidates.append(
                    SemanticCandidate(
                        kind="scope",
                        span=term,
                        path=path,
                        local_context=value,
                        deterministic_decision=SemanticCandidateDecision.ambiguous,
                        source=SemanticCandidateSource.ambiguous_term,
                        commitment_level=_infer_commitment_level(value),
                        reason="Scope-sensitive term needs semantic judgement.",
                    )
                )

    return _split_compound_scope_terms(_dedupe_candidates(candidates))


def run_semantic_guard(
    *,
    case_id: str,
    module: str,
    agent_output: dict[str, Any] | None,
    workspace_state: dict[str, Any],
    mode: SemanticGuardMode,
    judge_client: LLMClient | None,
    cache_dir: str | Path,
    use_cache: bool,
    judge_model: str,
    scope_contract: dict[str, list[str]] | None = None,
    judge_client_factory: Callable[[], LLMClient] | None = None,
) -> SemanticGuardReport:
    start = time.monotonic()
    if mode == SemanticGuardMode.off or not isinstance(agent_output, dict):
        return SemanticGuardReport(mode=mode, duration_seconds=round(time.monotonic() - start, 4))

    contract = scope_contract or DEFAULT_SCOPE_CONTRACT
    entity_candidates = extract_entity_candidates(agent_output, workspace_state)
    scope_candidates = extract_scope_candidates(agent_output, contract)
    candidates = entity_candidates + scope_candidates
    deterministic_findings = [
        finding for finding in (_finding_from_candidate(candidate) for candidate in candidates)
        if finding is not None
    ]
    ambiguous_candidates = [
        candidate
        for candidate in candidates
        if candidate.deterministic_decision == SemanticCandidateDecision.ambiguous
    ]

    report = SemanticGuardReport(
        mode=mode,
        called=False,
        findings=deterministic_findings,
        duration_seconds=round(time.monotonic() - start, 4),
    )
    _refresh_report_rollups(report)

    if report.hard_failures:
        return report

    if not ambiguous_candidates:
        return report

    owns_judge_client = False
    if judge_client is None and judge_client_factory is not None:
        try:
            judge_client = judge_client_factory()
            owns_judge_client = True
        except Exception as exc:
            _record_judge_infrastructure_diagnostic(
                report, mode,
                SemanticJudgeDiagnosticKind.judge_unavailable,
                f"Semantic judge client setup failed: {type(exc).__name__}: {exc}",
            )
            if mode == SemanticGuardMode.required:
                report.error_message = f"semantic judge required but client setup failed: {type(exc).__name__}"
            report.duration_seconds = round(time.monotonic() - start, 4)
            return report

    if judge_client is None:
        _record_judge_infrastructure_diagnostic(
            report, mode,
            SemanticJudgeDiagnosticKind.judge_unavailable,
            "Semantic judge required but no judge client is configured.",
        )
        if mode == SemanticGuardMode.required:
            report.error_message = "semantic judge required but no judge client is configured"
        report.duration_seconds = round(time.monotonic() - start, 4)
        return report

    judge_request = SemanticJudgeRequest(
        case_id=case_id,
        module=module,
        known_members=sorted(_known_workspace_members(workspace_state)),
        known_tasks=sorted(_known_workspace_tasks(workspace_state)),
        known_entities=sorted(build_workspace_entity_index(workspace_state).keys()),
        scope_contract=contract,
        candidates=ambiguous_candidates,
    )
    try:
        judge_report = run_semantic_judge(
            judge_request,
            client=judge_client,
            cache_dir=cache_dir,
            use_cache=use_cache,
            model=judge_model,
            mode=mode,
        )
    finally:
        if owns_judge_client and hasattr(judge_client, "close"):
            judge_client.close()
    report.called = judge_report.called
    report.cache_hit = judge_report.cache_hit
    report.error_message = judge_report.error_message
    report.diagnostics.extend(judge_report.diagnostics)

    if judge_report.error_message:
        # Infrastructure failure: do NOT create uncertain findings pretending
        # to be scope_creep/hallucinated_entity.  The diagnostic already records
        # the issue.  In required mode, the error_message is set.
        pass
    else:
        # ── Contradiction guard: downgrade entity FAIL findings where ────
        # ── the deterministic resolver finds the entity.                ──
        filtered_judge_findings = _filter_contradictory_judge_findings(
            judge_report.findings, workspace_state, report,
        )
        report.findings.extend(filtered_judge_findings)
    _refresh_report_rollups(report)
    report.duration_seconds = round(time.monotonic() - start, 4)
    return report


def _filter_contradictory_judge_findings(
    judge_findings: list[SemanticFinding],
    workspace_state: dict[str, Any],
    report: SemanticGuardReport,
) -> list[SemanticFinding]:
    """Filter out entity FAIL findings where the deterministic resolver finds the entity.

    When the semantic judge claims an entity is fabricated/hallucinated but the
    resolver says it exists, the finding is wrong.  Instead of passing it through
    as a hard failure, we:
    - Remove the finding (don't add to report.findings)
    - Add a ``judge_state_mismatch`` diagnostic explaining the contradiction
    """
    if not judge_findings:
        return judge_findings

    # Build entity index once — used for every finding
    index = build_workspace_entity_index(workspace_state)
    filtered: list[SemanticFinding] = []

    for finding in judge_findings:
        if (
            finding.kind == "entity"
            and finding.decision == SemanticDecision.fail
            and finding.span in index
        ):
            entry = index[finding.span]
            report.diagnostics.append(SemanticJudgeDiagnostic(
                kind=SemanticJudgeDiagnosticKind.judge_state_mismatch,
                message=(
                    f"Judge claimed entity '{finding.span}' was fabricated but "
                    f"deterministic resolver found it at {entry.state_path}."
                ),
                diagnostic_only=True,
                case_impact="none",
            ))
            continue  # skip this finding — it's a false positive from the judge
        filtered.append(finding)

    return filtered


def _record_judge_infrastructure_diagnostic(
    report: SemanticGuardReport,
    mode: SemanticGuardMode,
    kind: SemanticJudgeDiagnosticKind,
    message: str,
) -> None:
    """Add a judge infrastructure diagnostic to the report."""
    report.diagnostics.append(SemanticJudgeDiagnostic(
        kind=kind,
        message=message,
        diagnostic_only=True,
        case_impact="hard" if mode == SemanticGuardMode.required else "none",
    ))


def _finding_from_candidate(candidate: SemanticCandidate) -> SemanticFinding | None:
    if candidate.deterministic_decision != SemanticCandidateDecision.fail:
        return None
    category = (
        FailureCategory.scope_creep.value
        if candidate.kind == "scope"
        else FailureCategory.hallucinated_entity.value
    )
    return SemanticFinding(
        kind=candidate.kind,
        span=candidate.span,
        path=candidate.path,
        decision=SemanticDecision.fail,
        confidence=1.0,
        evidence=candidate.reason,
        failure_category=category,
        rule_id=f"semantic_{candidate.kind}_failure",
        severity="hard",
        source=candidate.source,
        risk=candidate.risk,
        commitment_level=candidate.commitment_level,
    )


def _uncertain_findings(candidates: list[SemanticCandidate], reason: str) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []
    for candidate in candidates:
        findings.append(
            SemanticFinding(
                kind=candidate.kind,
                span=candidate.span,
                path=candidate.path,
                decision=SemanticDecision.uncertain,
                confidence=0.0,
                evidence=reason,
                failure_category=(
                    FailureCategory.scope_creep.value
                    if candidate.kind == "scope"
                    else FailureCategory.hallucinated_entity.value
                ),
                rule_id=f"semantic_{candidate.kind}_uncertain",
                severity="uncertain",
                source=candidate.source,
                risk=candidate.risk,
                commitment_level=candidate.commitment_level,
            )
        )
    return findings


def _refresh_report_rollups(report: SemanticGuardReport) -> None:
    report.uncertain_count = sum(
        1 for finding in report.findings
        if finding.decision == SemanticDecision.uncertain
    )
    report.hard_failures = [
        finding.rule_id or f"semantic_{finding.kind}_failure"
        for finding in report.findings
        if finding.is_hard_failure
    ]
    report.failure_categories = sorted({
        finding.failure_category
        for finding in report.findings
        if finding.is_hard_failure and finding.failure_category
    })


def _known_workspace_tokens(workspace_state: dict[str, Any]) -> set[str]:
    known: set[str] = set()
    known.update(_known_workspace_members(workspace_state))
    project = workspace_state.get("project", {})
    if isinstance(project, dict):
        if project.get("id"):
            known.add(str(project["id"]))
        for collection in ("stages", "tasks", "resources", "assignment_proposals"):
            for item in project.get(collection, []):
                if isinstance(item, dict):
                    for key in ("id", "name", "title"):
                        if item.get(key):
                            known.add(str(item[key]))
    return known


def _output_defined_ids(agent_output: dict[str, Any]) -> set[str]:
    defined: set[str] = set()
    for path, value in _walk(agent_output):
        if not isinstance(value, str):
            continue
        if _path_key(path) not in {"id", "proposal_id"}:
            continue
        if _ID_RE.fullmatch(value):
            defined.add(value)
    return defined


def _path_key(path: str) -> str:
    normalized = re.sub(r"\[\d+\]", "", path)
    return normalized.rsplit(".", 1)[-1]


def _known_workspace_members(workspace_state: dict[str, Any]) -> set[str]:
    known: set[str] = set()
    for member in workspace_state.get("members", []):
        if isinstance(member, dict):
            for key in ("user_id", "display_name"):
                if member.get(key):
                    known.add(str(member[key]))
    return known


def _known_workspace_tasks(workspace_state: dict[str, Any]) -> set[str]:
    project = workspace_state.get("project", {})
    if not isinstance(project, dict):
        return set()
    tasks: set[str] = set()
    for task in project.get("tasks", []):
        if isinstance(task, dict):
            for key in ("id", "title"):
                if task.get(key):
                    tasks.add(str(task[key]))
    return tasks


def _walk(value: Any, path: str = "agent_output") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        items: list[tuple[str, Any]] = []
        for key, child in value.items():
            items.extend(_walk(child, f"{path}.{key}"))
        return items
    if isinstance(value, list):
        items = []
        for index, child in enumerate(value):
            items.extend(_walk(child, f"{path}[{index}]"))
        return items
    return [(path, value)]


def _find_key(value: Any, key: str, path: str = "agent_output") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        found: list[tuple[str, Any]] = []
        for child_key, child in value.items():
            child_path = f"{path}.{child_key}"
            if child_key == key:
                found.append((child_path, child))
            found.extend(_find_key(child, key, child_path))
        return found
    if isinstance(value, list):
        found = []
        for index, child in enumerate(value):
            found.extend(_find_key(child, key, f"{path}[{index}]"))
        return found
    return []


def _local_context(text: str, start: int, end: int) -> str:
    return text[max(0, start - 30): min(len(text), end + 30)]


def _looks_like_time_or_range_context(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 12):start]
    after = text[end:end + 8]
    compact_before = re.sub(r"\s+", "", before)
    compact_after = re.sub(r"\s+", "", after)
    return (
        "/" in before
        or "／" in before
        or any(unit in compact_before for unit in ("小时", "天", "周", "月", "阶段", "范围", "版本"))
        or any(compact_after.startswith(marker) for marker in ("内", "以内", "之内", "前", "后"))
    )


_COMMON_SURNAME_CHARS = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟"
    "平黄和穆萧尹姚邵汪毛米贝戴宋庞熊纪舒项祝董梁杜阮蓝闵席季贾路"
)
_COMPOUND_SURNAMES = ("欧阳", "司马", "上官", "诸葛", "东方", "夏侯", "皇甫", "尉迟")
_NON_PERSON_SPANS = {
    "手段", "功能", "功能的", "功能在", "资料", "资料的", "列表", "设计", "协作",
    "尚未", "后端", "前端", "接口", "页面", "产品", "团队", "成员", "任务", "阶段",
    "范围", "版本", "系统", "项目", "用户", "数据", "课程", "搜索", "评价",
}
_ROLE_MARKERS = ("负责人", "同学", "团队", "成员", "角色", "岗位")


def _looks_like_person_name(span: str) -> bool:
    if span in _NON_PERSON_SPANS or any(marker in span for marker in _ROLE_MARKERS):
        return False
    if len(span) < 2 or len(span) > 3:
        return False
    if span.startswith(("小", "老")) and len(span) in {2, 3}:
        return True
    if any(span.startswith(surname) for surname in _COMPOUND_SURNAMES):
        return True
    return span[0] in _COMMON_SURNAME_CHARS


def _path_is_non_committal(path: str) -> bool:
    normalized = path.replace("[", ".").replace("]", "")
    parts = {part for part in normalized.split(".") if part and not part.isdigit()}
    return bool(parts.intersection({"boundaries", "mvp_boundary", "out_of_scope", "defer", "unknowns"}))


def _is_future_direction(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return any(marker in compact for marker in ("后续可探索", "未来可考虑", "暂不实现", "后续迭代", "可选方向"))


def _looks_like_web_compatibility_context(text: str) -> bool:
    compact = re.sub(r"\s+", "", text).lower()
    return "桌面端" in text and any(
        marker in compact
        for marker in ("浏览器", "响应式", "web", "页面适配", "页面响应式")
    )


def _infer_commitment_level(text: str) -> ScopeCommitmentLevel:
    compact = re.sub(r"\s+", "", text)
    if any(marker in compact for marker in ("后续可探索", "未来可考虑", "后续迭代")):
        return ScopeCommitmentLevel.optional_future_direction
    if any(marker in compact for marker in ("适配", "兼容", "主流浏览器")):
        return ScopeCommitmentLevel.compatibility_note
    if any(marker in compact for marker in ("必须", "mvp", "MVP", "交付", "实现", "对接", "集成")):
        return ScopeCommitmentLevel.implementation_commitment
    return ScopeCommitmentLevel.description


_COMPOUND_CONJUNCTIONS = ("和", "与", "及", "、", "跟", "以及", "或", "还是")


def _split_compound_scope_terms(
    candidates: list[SemanticCandidate],
) -> list[SemanticCandidate]:
    """Split compound scope terms like '移动端和桌面端' into separate candidates.

    Preserves local_context (trimmed to each split span) and commitment_level.
    Only splits for ambiguous-scope candidates where the span contains multiple
    scope-relevant terms joined by conjunctions.
    """
    split: list[SemanticCandidate] = []
    for candidate in candidates:
        span = candidate.span
        context = candidate.local_context
        # Only split ambiguous scope candidates with compounds
        if (
            candidate.kind != "scope"
            or candidate.deterministic_decision != SemanticCandidateDecision.ambiguous
        ):
            split.append(candidate)
            continue
        parts = _split_by_conjunction(span)
        if len(parts) <= 1:
            split.append(candidate)
            continue
        for part in parts:
            part_stripped = part.strip()
            if not part_stripped:
                continue
            # Preserve the original context, trim to the part's vicinity
            local_ctx = _trim_context_to_term(context, span, part_stripped)
            split.append(SemanticCandidate(
                kind="scope",
                span=part_stripped,
                path=candidate.path,
                local_context=local_ctx,
                deterministic_decision=SemanticCandidateDecision.ambiguous,
                source=candidate.source,
                risk=candidate.risk,
                commitment_level=candidate.commitment_level,
                reason=candidate.reason,
            ))
    return _dedupe_candidates(split)


def _split_by_conjunction(text: str) -> list[str]:
    """Split a span by Chinese conjunctions like '和', '与', '、'."""
    # Build pattern from conjunctions
    conj_pattern = "|".join(re.escape(c) for c in _COMPOUND_CONJUNCTIONS)
    parts = re.split(conj_pattern, text)
    return [p.strip() for p in parts if p.strip()]


def _trim_context_to_term(
    full_context: str,
    original_span: str,
    target_term: str,
) -> str:
    """Trim local context to the vicinity of a target term within the original span."""
    idx = full_context.find(target_term)
    if idx == -1:
        return full_context[:_RAW_EXCERPT_LEN] if len(full_context) > _RAW_EXCERPT_LEN else full_context
    start = max(0, idx - 20)
    end = min(len(full_context), idx + len(target_term) + 20)
    return full_context[start:end]


def _dedupe_candidates(candidates: list[SemanticCandidate]) -> list[SemanticCandidate]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[SemanticCandidate] = []
    for candidate in candidates:
        key = (candidate.kind, candidate.span, candidate.path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped
