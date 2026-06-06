"""Lightweight LLM semantic judge for AgentEval v2.1."""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agent.llm_client import LLMClient, LLMClientSettings, build_llm_client
from app.agent_eval.schemas import (
    SemanticFinding, SemanticGuardMode, SemanticGuardReport,
    SemanticJudgeDiagnostic, SemanticJudgeDiagnosticKind,
)
from app.core.config import settings as app_settings

SEMANTIC_GUARD_VERSION = '2.1.1'
SEMANTIC_JUDGE_PROMPT_VERSION = '2026-06-07.v1'


class SemanticJudgeRequest(BaseModel):
    case_id: str
    module: str
    known_members: list[str] = Field(default_factory=list)
    known_tasks: list[str] = Field(default_factory=list)
    known_entities: list[str] = Field(default_factory=list, description="All known entity IDs from the workspace, for deterministic resolution.")
    scope_contract: dict[str, Any] = Field(default_factory=dict)
    candidates: list[Any] = Field(default_factory=list)

class _SemanticJudgeResponseInternal(BaseModel):
    findings: list[SemanticFinding] = Field(default_factory=list)
    overall_decision: str = 'UNCERTAIN'
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


_FORBIDDEN_INFRA_CATEGORIES = {
    "schema_failure", "invalid_schema", "json_error",
    "validation_error", "infrastructure_error",
}
_FORBIDDEN_INFRA_DECISIONS = {
    "SCHEMA_ERROR", "VALIDATION_ERROR", "JSON_ERROR", "INTERNAL_ERROR",
}
_DECISION_ALIASES: dict[str, str] = {
    "ok": "PASS",
    "passed": "PASS",
    "pass_with_note": "PASS",
    "violation": "FAIL",
    "failed": "FAIL",
    "failure": "FAIL",
    "schema_error": "UNCERTAIN",
    "validation_error": "UNCERTAIN",
    "json_error": "UNCERTAIN",
    "error": "UNCERTAIN",
    "unknown": "UNCERTAIN",
}
_FORBIDDEN_SCOPE_CATEGORIES = {
    "schema_failure", "invalid_schema", "json_error",
    "validation_error", "infrastructure_failure",
}
_FORBIDDEN_ENTITY_CATEGORIES = {
    "schema_failure", "invalid_schema", "json_error",
    "validation_error", "infrastructure_failure",
}
# Category aliases that should be normalized to canonical values
_CATEGORY_ALIASES_SCOPE: dict[str, str] = {
    "mvp_violation": "scope_creep",
    "out_of_scope": "scope_creep",
    "out_of_mvp": "scope_creep",
    "mobile_app": "scope_creep",
    "desktop_app": "scope_creep",
    "native_app": "scope_creep",
    "external_integration": "scope_creep",
}
_CATEGORY_ALIASES_ENTITY: dict[str, str] = {
    "unknown_entity": "hallucinated_entity",
    "unknown_id": "hallucinated_entity",
    "fabricated_entity": "hallucinated_entity",
}
_RAW_EXCERPT_MAX_LEN = 500


def build_semantic_judge_client(
    *,
    model: str | None = None,
    base_url: str | None = None,
) -> LLMClient:
    api_key = (
        app_settings.semantic_judge_api_key.get_secret_value()
        if app_settings.semantic_judge_api_key
        else app_settings.llm_api_key.get_secret_value()
        if app_settings.llm_api_key
        else None
    )
    selected_base_url = base_url or app_settings.semantic_judge_base_url or app_settings.llm_base_url
    selected_model = model or app_settings.semantic_judge_model
    provider = app_settings.semantic_judge_provider or app_settings.llm_provider
    return build_llm_client(
        LLMClientSettings(
            provider=provider,
            api_key=api_key,
            base_url=selected_base_url,
            model=selected_model,
            timeout_seconds=app_settings.semantic_judge_timeout_seconds,
        )
    )


def build_semantic_judge_cache_key(
    request: SemanticJudgeRequest,
    *,
    model: str,
    prompt_version: str = SEMANTIC_JUDGE_PROMPT_VERSION,
) -> str:
    payload = {
        'version': SEMANTIC_GUARD_VERSION,
        'prompt_version': prompt_version,
        'model': model,
        'request': request.model_dump(mode='json'),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()

def run_semantic_judge(
    request: SemanticJudgeRequest,
    *,
    client: LLMClient,
    cache_dir: str | Path,
    use_cache: bool,
    model: str,
    mode: SemanticGuardMode = SemanticGuardMode.auto,
) -> SemanticGuardReport:
    start = time.monotonic()
    cache_key = build_semantic_judge_cache_key(request, model=model)
    cache_path = Path(cache_dir) / 'semantic-judge' / f'{cache_key}.json'
    if use_cache and cache_path.exists():
        try:
            cached = SemanticGuardReport.model_validate_json(cache_path.read_text(encoding='utf-8'))
            cached.cache_hit = True
            return cached
        except (OSError, ValidationError):
            pass

    report = SemanticGuardReport(mode=mode, called=True)
    try:
        response_text = client.complete(_build_messages(request), max_tokens=1800)
        parsed, diagnostics = parse_semantic_judge_response(response_text)
        report.diagnostics.extend(diagnostics)
        if parsed is not None:
            report.findings = parsed.findings
            report.uncertain_count = sum(1 for f in parsed.findings if f.decision.value == 'UNCERTAIN')
            report.hard_failures = [
                f.rule_id or f'semantic_{f.kind}_failure'
                for f in parsed.findings
                if f.is_hard_failure
            ]
            report.failure_categories = sorted({
                f.failure_category
                for f in parsed.findings
                if f.is_hard_failure and f.failure_category
            })
        else:
            # Parser returned None + a diagnostic — report stays in error state
            if not report.error_message and diagnostics:
                kind_str = diagnostics[0].kind.value
                report.error_message = f'semantic judge unavailable: {kind_str}'
    except TimeoutError:
        report.error_message = 'semantic judge unavailable: judge_timeout'
        report.diagnostics.append(SemanticJudgeDiagnostic(
            kind=SemanticJudgeDiagnosticKind.judge_timeout,
            message='Semantic judge call timed out.',
        ))
    except Exception as exc:
        report.error_message = f'semantic judge unavailable: {type(exc).__name__}'
        report.diagnostics.append(SemanticJudgeDiagnostic(
            kind=SemanticJudgeDiagnosticKind.judge_unavailable,
            message=str(exc),
        ))
    finally:
        report.duration_seconds = round(time.monotonic() - start, 4)

    if use_cache and not report.error_message:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(report.model_dump_json(indent=2, exclude_none=True), encoding='utf-8')
    return report


def parse_semantic_judge_response(
    response_text: str,
) -> tuple[_SemanticJudgeResponseInternal | None, list[SemanticJudgeDiagnostic]]:
    """Parse, normalize, and validate a semantic judge response.

    Returns (parsed_response or None, diagnostics).
    When parsing fails, returns (None, [diagnostic]) — the caller must not
    create normal SemanticFinding objects from infrastructure errors.
    """
    diagnostics: list[SemanticJudgeDiagnostic] = []
    raw_excerpt = response_text[:_RAW_EXCERPT_MAX_LEN]

    # Try to extract a JSON object from the raw text (handles prose/fenced code)
    payload: dict[str, Any] | None = None
    try:
        payload = _extract_first_json(response_text)
    except Exception:
        diagnostics.append(SemanticJudgeDiagnostic(
            kind=SemanticJudgeDiagnosticKind.judge_json_parse_error,
            message="Could not extract a JSON object from judge response text.",
            raw_excerpt=raw_excerpt,
        ))
        return None, diagnostics

    if payload is None:
        diagnostics.append(SemanticJudgeDiagnostic(
            kind=SemanticJudgeDiagnosticKind.judge_json_parse_error,
            message="No JSON object found in judge response.",
            raw_excerpt=raw_excerpt,
        ))
        return None, diagnostics

    # Normalise top-level shape aliases
    _normalize_shape_aliases(payload)
    # Normalise category aliases to canonical values
    _normalize_category_aliases(payload)
    # Normalise decisions across all findings
    _normalize_finding_decisions(payload)
    # Forbid infrastructure failure categories
    _filter_infrastructure_categories(payload, diagnostics)

    # If *all* findings were removed, track that.
    original_findings = list(payload.get("findings", []))

    try:
        parsed = _SemanticJudgeResponseInternal.model_validate(payload)
    except ValidationError as exc:
        diagnostics.append(SemanticJudgeDiagnostic(
            kind=SemanticJudgeDiagnosticKind.judge_schema_error,
            message=f"Semantic judge response failed validation: {exc}",
            candidate_count=len(original_findings),
            raw_excerpt=raw_excerpt,
        ))
        return None, diagnostics

    return parsed, diagnostics


def _extract_first_json(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from text, stripping prose/fence markers."""
    # Try full parse first
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Try fenced JSON block
    fence_match = re.search(r"```(?:json)?\s*\n?(\{.*?\})\s*\n?```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try first { ... } block in the text
    brace_match = re.search(r"(\{.*\})", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(1))
        except json.JSONDecodeError:
            pass

    return None


def _normalize_shape_aliases(payload: dict[str, Any]) -> None:
    """Normalise shape aliases: scope_findings/entity_findings -> findings,
    result/status/verdict -> decision, reason/rationale/explanation -> evidence."""
    # Merge scope_findings / entity_findings into findings
    alternate_finding_keys = ["scope_findings", "entity_findings"]
    merged = list(payload.get("findings", []))
    for key in alternate_finding_keys:
        items = payload.get(key, [])
        if items and isinstance(items, list):
            # Tag each finding with its inferred kind
            for item in items:
                if isinstance(item, dict) and "kind" not in item:
                    kind = key.replace("_findings", "")
                    item["kind"] = kind
                merged.append(item)
            payload.pop(key, None)
    if merged:
        payload["findings"] = merged

    # Normalise decision key
    for alias in ("result", "status", "verdict", "overall_decision_upper"):
        val = payload.pop(alias, None)
        if val is not None and "overall_decision" not in payload:
            payload["overall_decision"] = _normalize_decision_value(str(val))

    # Normalise evidence key on findings
    for finding in payload.get("findings", []):
        if isinstance(finding, dict):
            # Map result/status/verdict -> decision at finding level
            for alias in ("result", "status", "verdict"):
                val = finding.pop(alias, None)
                if val is not None and not finding.get("decision"):
                    finding["decision"] = _normalize_decision_value(str(val))
            # Map reason/rationale/explanation -> evidence at finding level
            for alias in ("reason", "rationale", "explanation"):
                val = finding.pop(alias, None)
                if val is not None and not finding.get("evidence"):
                    finding["evidence"] = str(val)


def _normalize_finding_decisions(payload: dict[str, Any]) -> None:
    """Normalise decision values across all findings."""
    top_level = payload.get("overall_decision", "")
    payload["overall_decision"] = _normalize_decision_value(top_level)

    for finding in payload.get("findings", []):
        if isinstance(finding, dict) and "decision" in finding:
            raw = finding["decision"]
            normalized = _normalize_decision_value(str(raw))
            finding["decision"] = normalized


def _normalize_decision_value(raw: str) -> str:
    """Normalise a single decision string."""
    upper = raw.strip().upper()
    if upper in _FORBIDDEN_INFRA_DECISIONS:
        return "UNCERTAIN"
    return _DECISION_ALIASES.get(upper.lower(), upper)


def _normalize_category_aliases(payload: dict[str, Any]) -> None:
    """Normalize category aliases to canonical values.

    Maps judge output category aliases like mvp_violation/out_of_scope
    to scope_creep for scope findings, unknown_entity/unknown_id/fabricated_entity
    to hallucinated_entity for entity findings, when the finding is a real FAIL
    with evidence/path/confidence.
    """
    findings = payload.get("findings", [])
    if not isinstance(findings, list):
        return

    for finding in findings:
        if not isinstance(finding, dict):
            continue
        cat = finding.get("failure_category")
        if not cat or not isinstance(cat, str):
            continue
        cat_lower = cat.lower().strip()
        kind = finding.get("kind", "").lower()
        decision = str(finding.get("decision", "")).upper().strip()
        evidence = str(finding.get("evidence", "") or "").strip()
        path = str(finding.get("path", "") or "").strip()
        confidence = float(finding.get("confidence", 0.0) or 0.0)

        is_real_fail = (
            decision == "FAIL" and evidence and path and confidence >= 0.75
        )

        if kind == "scope" and cat_lower in _CATEGORY_ALIASES_SCOPE:
            finding["failure_category"] = _CATEGORY_ALIASES_SCOPE[cat_lower]
        elif kind == "entity" and cat_lower in _CATEGORY_ALIASES_ENTITY:
            finding["failure_category"] = _CATEGORY_ALIASES_ENTITY[cat_lower]
        elif (
            cat_lower in _CATEGORY_ALIASES_SCOPE
            and is_real_fail
            and kind == "scope"
        ):
            finding["failure_category"] = _CATEGORY_ALIASES_SCOPE[cat_lower]
        elif (
            cat_lower in _CATEGORY_ALIASES_ENTITY
            and is_real_fail
            and kind == "entity"
        ):
            finding["failure_category"] = _CATEGORY_ALIASES_ENTITY[cat_lower]


def _filter_infrastructure_categories(
    payload: dict[str, Any],
    diagnostics: list[SemanticJudgeDiagnostic],
) -> None:
    """Forbid infrastructure failure categories in semantic findings.

    schema_failure, invalid_schema, json_error, validation_error must not
    appear as SemanticFinding.failure_category. They are remapped to None
    (scope findings) or hallucinated_entity (entity findings with FAIL+threshold),
    or left as None.
    """
    findings = payload.get("findings", [])
    if not isinstance(findings, list):
        return

    filtered: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        cat = finding.get("failure_category")
        if cat and cat.lower() in _FORBIDDEN_INFRA_CATEGORIES:
            kind = finding.get("kind", "").lower()
            decision = str(finding.get("decision", "")).upper().strip()
            confidence = float(finding.get("confidence", 0.0) or 0.0)
            evidence = str(finding.get("evidence", "") or "").strip()
            path = str(finding.get("path", "") or "").strip()

            diagnostics.append(SemanticJudgeDiagnostic(
                kind=SemanticJudgeDiagnosticKind.judge_contract_violation,
                message=(
                    f"Judge used infrastructure category '{cat}' for {kind} "
                    f"finding '{finding.get('span', '')}'. "
                    "Infrastructure categories are forbidden in semantic findings."
                ),
            ))

            # For entity findings with FAIL + threshold, map to hallucinated_entity
            if kind == "entity" and decision == "FAIL" and evidence and path and confidence >= 0.75:
                finding["failure_category"] = "hallucinated_entity"
                # Also clear diagnostic_only flag — this is a real finding
            elif kind == "scope" and decision == "FAIL" and evidence and path and confidence >= 0.75:
                finding["failure_category"] = "scope_creep"
            else:
                # Cannot salvage — clear the category
                finding["failure_category"] = None
                # If no decision quality remains, mark uncertainty
                if finding.get("decision") in ("PASS", "FAIL"):
                    pass  # keep original decision, just drop the bad category
        filtered.append(finding)
    payload["findings"] = filtered

def _build_messages(request: SemanticJudgeRequest) -> list[dict[str, str]]:
    system = (
        "You are a strict benchmark semantic guard for ProjectFlow AgentEval. "
        "Only judge the provided candidates. Return JSON only. "
        "Use decisions PASS, FAIL, or UNCERTAIN. "
        "You are not evaluating the Agent quality in general. "
        "Do not introduce new candidates. "
        "Do not fail unless the candidate clearly violates the contract. "
        "If evidence is weak, return UNCERTAIN. "
        "Use PASS when the span is merely mentioned but not committed as an MVP deliverable. "
        "Use PASS when the span is a compatibility note, background description, or explicitly deferred. "
        "Use FAIL only when the output makes a concrete unsupported assignment or scope commitment. "
        "A FAIL requires concrete evidence and confidence. "
        "Never invent members, tasks, or scope rules. "
        "CRITICAL: Entity ID existence (task-N, user-N, stage-N, prop-N) is decided by the "
        "deterministic resolver, NOT by you. If a candidate's span matches a known entity ID "
        "in the known_entities list, do NOT classify it as fabricated — it already exists "
        "deterministically. You only assess semantic reasoning quality about the candidate."
    )
    user = {
        'case_id': request.case_id,
        'module': request.module,
        'known_members': request.known_members,
        'known_tasks': request.known_tasks,
        'known_entities': sorted(request.known_entities) if request.known_entities else [],
        'scope_contract': request.scope_contract,
        'candidates': [
            c.model_dump(mode="json") if hasattr(c, "model_dump") else c
            for c in request.candidates
        ],
        'required_json_schema': {
            "findings": [
                {
                    "kind": "entity|scope",
                    "span": "candidate span",
                    "path": "candidate path",
                    "decision": "PASS|FAIL|UNCERTAIN",
                    "confidence": 0.0,
                    "evidence": "short evidence",
                    "source": "candidate source",
                    "severity": "hard|soft|uncertain",
                    "risk": "high|medium|low|null",
                    "commitment_level": "description|compatibility_note|optional_future_direction|mvp_required_deliverable|implementation_commitment|null",
                    "failure_category": "hallucinated_entity|scope_creep|null",
                    "rule_id": "semantic_entity_failure|semantic_scope_failure",
                }
            ],
            "overall_decision": "PASS|FAIL|UNCERTAIN",
            "confidence": 0.0,
            "prompt_version": SEMANTIC_JUDGE_PROMPT_VERSION,
        },
        "judge_constraints_zh": [
            "你不是在整体评价 Agent 回答质量。",
            "你只判断传入的 candidates。",
            "不要自行发现新问题。",
            "证据不足时输出 UNCERTAIN。",
            "仅当 candidate 明确违反 scope contract 或明确构造不存在实体时输出 FAIL。",
            "如果只是兼容性描述、背景说明、后续可选方向，不应判为 MVP scope creep。",
        ],
        "judge_infrastructure_constraint": [
            "IMPORTANT: Never output schema_failure, invalid_schema, json_error, or validation_error as category values.",
            "These are deterministic validator categories, not semantic judge categories.",
            "For MVP boundary violations, use failure_category: scope_creep.",
            "For uncertain cases, use decision: UNCERTAIN, not an error category.",
            "Do not encode infrastructure errors (schema, json, validation) as semantic findings.",
        ],
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]
