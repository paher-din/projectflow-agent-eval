"""Pydantic models for Agent Evaluation Benchmark case fixtures, validator results,
judge results, and report artifacts.

v2 adds assertion-based evaluation models alongside v1 rubric models.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Failure taxonomy (shared classification)
# ---------------------------------------------------------------------------

class FailureCategory(str, Enum):
    context_missing = "context_missing"
    context_ignored = "context_ignored"
    hallucinated_entity = "hallucinated_entity"
    scope_creep = "scope_creep"
    wrong_module_behavior = "wrong_module_behavior"
    weak_actionability = "weak_actionability"
    weak_explainability = "weak_explainability"
    schema_failure = "schema_failure"
    repair_failure = "repair_failure"
    fallback_quality_failure = "fallback_quality_failure"
    persistence_boundary_violation = "persistence_boundary_violation"
    date_time_error = "date_time_error"
    judge_failure = "judge_failure"
    dependency_inconsistency = "dependency_inconsistency"
    no_op_replan = "no_op_replan"
    missing_assertion_evidence = "missing_assertion_evidence"


# ---------------------------------------------------------------------------
# Semantic Guard models (v2.1)
# ---------------------------------------------------------------------------

class SemanticGuardMode(str, Enum):
    off = "off"
    auto = "auto"
    required = "required"


class SemanticJudgeDiagnosticKind(str, Enum):
    judge_schema_error = "judge_schema_error"
    judge_json_parse_error = "judge_json_parse_error"
    judge_timeout = "judge_timeout"
    judge_contract_violation = "judge_contract_violation"
    judge_unavailable = "judge_unavailable"
    judge_state_mismatch = "judge_state_mismatch"


class SemanticJudgeDiagnostic(BaseModel):
    kind: SemanticJudgeDiagnosticKind
    message: str = ""
    candidate_count: int = 0
    case_impact: str = "none"  # "none" | "soft" | "hard"
    diagnostic_only: bool = True
    raw_excerpt: str = ""


class SemanticDecision(str, Enum):
    pass_ = "PASS"
    fail = "FAIL"
    uncertain = "UNCERTAIN"


class SemanticCandidateDecision(str, Enum):
    pass_ = "PASS"
    fail = "FAIL"
    ambiguous = "AMBIGUOUS"


class SemanticCandidateSource(str, Enum):
    structured_field = "structured_field"
    id_pattern = "id_pattern"
    text_trigger = "text_trigger"
    scope_keyword = "scope_keyword"
    ambiguous_term = "ambiguous_term"
    time_or_range_pattern = "time_or_range_pattern"


class SemanticRisk(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class SemanticSeverity(str, Enum):
    hard = "hard"
    soft = "soft"
    uncertain = "uncertain"


class ScopeCommitmentLevel(str, Enum):
    description = "description"
    compatibility_note = "compatibility_note"
    optional_future_direction = "optional_future_direction"
    mvp_required_deliverable = "mvp_required_deliverable"
    implementation_commitment = "implementation_commitment"


class SemanticCandidate(BaseModel):
    kind: str
    span: str
    path: str
    local_context: str = ""
    deterministic_decision: SemanticCandidateDecision = SemanticCandidateDecision.ambiguous
    source: SemanticCandidateSource = SemanticCandidateSource.ambiguous_term
    risk: SemanticRisk | None = None
    commitment_level: ScopeCommitmentLevel | None = None
    reason: str = ""


class SemanticFinding(BaseModel):
    kind: str
    span: str
    path: str
    decision: SemanticDecision
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str = ""
    failure_category: str | None = None
    rule_id: str = ""
    severity: SemanticSeverity | None = None
    source: SemanticCandidateSource | None = None
    risk: SemanticRisk | None = None
    commitment_level: ScopeCommitmentLevel | None = None

    @property
    def is_hard_failure(self) -> bool:
        return (
            self.decision == SemanticDecision.fail
            and (self.severity is None or self.severity == SemanticSeverity.hard)
            and self.confidence >= 0.75
            and bool(self.evidence.strip())
            and (bool(self.path.strip()) or bool(self.span.strip()))
        )


class SemanticGuardReport(BaseModel):
    mode: SemanticGuardMode = SemanticGuardMode.auto
    called: bool = False
    cache_hit: bool = False
    duration_seconds: float = 0.0
    uncertain_count: int = 0
    findings: list[SemanticFinding] = Field(default_factory=list)
    hard_failures: list[str] = Field(default_factory=list)
    failure_categories: list[str] = Field(default_factory=list)
    error_message: str = ""
    diagnostics: list[SemanticJudgeDiagnostic] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# v2 Assertion models
# ---------------------------------------------------------------------------

class AssertionSeverity(str, Enum):
    """Severity of an assertion failure."""
    hard = "hard"      # Case fails regardless of weighted score
    major = "major"    # Large score penalty (-8 to -15)
    minor = "minor"    # Small score penalty (-2 to -5)
    info = "info"      # Diagnostic only (no direct penalty)


class AssertionEvaluator(str, Enum):
    """Evaluator type for an assertion."""
    schema = "schema"
    deterministic_text = "deterministic_text"
    deterministic_date = "deterministic_date"
    state_path = "state_path"
    graph = "graph"
    diff = "diff"
    trace = "trace"
    llm_semantic = "llm_semantic"
    stability = "stability"


class AssertionTarget(str, Enum):
    """What the assertion targets."""
    agent_output = "agent_output"
    workspace_state = "workspace_state"
    trace = "trace"
    prompt_context = "prompt_context"


DEFAULT_PENALTY_MAP: dict[str, float] = {
    "hard": 0.0,    # Hard failures fail the case; preserved for score tracking
    "major": -10.0,
    "minor": -3.0,
    "info": 0.0,
}


class Assertion(BaseModel):
    """A single atomic assertion in a v2 benchmark case."""

    id: str = Field(..., min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    group: str = Field(default="general", min_length=1)
    severity: AssertionSeverity = AssertionSeverity.major
    evaluator: AssertionEvaluator = AssertionEvaluator.deterministic_text
    target: AssertionTarget = AssertionTarget.agent_output
    rule: str = Field(default="required_terms_present", min_length=1)
    expected: list[str] | None = None
    forbidden: list[str] | None = None
    required: list[str] | None = None
    evidence_paths: list[str] | None = None
    failure_category: str | None = FailureCategory.schema_failure.value
    remediation_hint: str | None = None
    payload: dict[str, Any] | None = None  # Extra evaluator-specific config

    @field_validator("id")
    @classmethod
    def id_must_match_pattern(cls, v: str) -> str:
        return v


class AssertionResult(BaseModel):
    """Result of evaluating a single assertion."""

    assertion_id: str
    status: str  # "passed", "failed", "skipped"
    severity: AssertionSeverity
    score_delta: float = 0.0
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    failure_category: str | None = None
    remediation_hint: str | None = None
    detail: str = ""


class AssertionPack(BaseModel):
    """Collection of assertions for a benchmark case fixture."""
    assertions: list[Assertion] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Run config
# ---------------------------------------------------------------------------

class RunConfig(BaseModel):
    mode: str = "mock"  # "mock" or "real"
    model: str = ""
    provider: str = ""
    base_url_host: str = ""
    judge_mode: str = "auto"
    cache_enabled: bool = False
    cache_dir: str = ""
    resume_from: str = ""
    retry_from: str = ""
    retry_mode: str = ""
    temperature: float = 0.0
    max_tokens: int = 4000
    output_dir: str = "output/agent-eval"
    runs_per_case: int = 1
    case_ids: list[str] = Field(default_factory=list)
    # v2.1 semantic guard
    semantic_guard_mode: SemanticGuardMode = SemanticGuardMode.auto
    semantic_judge_model: str = ""
    semantic_judge_base_url_host: str = ""
    semantic_judge_prompt_version: str = ""
    # External ProjectFlow Agent source (set via --projectflow-root)
    projectflow_source_path: str = ""
    projectflow_git_commit: str = ""
    agent_model: str = ""


# ---------------------------------------------------------------------------
# Case fixture (v1 + v2)
# ---------------------------------------------------------------------------

class RubricWeights(BaseModel):
    context_grounding: float = 0.0
    mvp_boundary: float = 0.0
    actionability: float = 0.0
    module_fit: float = 0.0
    explainability: float = 0.0
    reliability: float = 0.0
    language_quality: float = 0.0
    # Module-specific dimensions (parsed from extras)
    clarification_quality: float = 0.0
    unknown_detection: float = 0.0
    decision_point_quality: float = 0.0
    stage_coherence: float = 0.0
    deadline_awareness: float = 0.0
    deliverable_alignment: float = 0.0
    task_granularity: float = 0.0
    dependency_simplicity: float = 0.0
    priority_boundary: float = 0.0
    member_fit: float = 0.0
    availability_awareness: float = 0.0
    confirmation_safety: float = 0.0
    swap_reasoning: float = 0.0
    timeline_only_persistence: float = 0.0
    participant_grounding: float = 0.0
    next_action_quality: float = 0.0
    start_guidance: float = 0.0
    done_when_quality: float = 0.0
    evidence_quality: float = 0.0
    severity_calibration: float = 0.0
    risk_type_fit: float = 0.0
    before_after_quality: float = 0.0
    impact_explanation: float = 0.0
    confirmation_requirement: float = 0.0

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "RubricWeights":
        total = sum(
            v for k, v in self.model_dump().items()
            if v is not None and v != 0.0
        )
        if total == 0.0:
            return self
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Rubric weights must sum to 1.0, got {total}")
        return self

    def active_dimensions(self) -> dict[str, float]:
        """Return only dimensions with non-zero weight."""
        return {k: v for k, v in self.model_dump().items() if v and v > 0.0}


class HardFailRule(str, Enum):
    invalid_schema = "invalid_schema"
    missing_status = "missing_status"
    fabricated_workspace_entity = "fabricated_workspace_entity"
    violates_mvp_boundary = "violates_mvp_boundary"
    unsafe_persistence = "unsafe_persistence"
    negotiate_created_generic_proposal = "negotiate_created_generic_proposal"
    missing_reason = "missing_reason"
    empty_fallback = "empty_fallback"
    date_miscalculation = "date_miscalculation"
    unlabeled_fallback = "unlabeled_fallback"


class EvalCase(BaseModel):
    id: str = Field(..., min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(..., min_length=1)
    module: str = Field(..., min_length=1)
    entrypoint: str = Field(..., min_length=1)
    workspace_state: dict[str, Any]
    expected_behavior: list[str] = Field(min_length=1)
    forbidden_behavior: list[str] = Field(default_factory=list)
    rubric_weights: RubricWeights
    minimum_score: float = Field(default=0.8, ge=0.0, le=1.0)
    hard_fail_rules: list[HardFailRule] = Field(default_factory=list)
    # v2 assertion pack (backward-compatible: empty list means no assertions)
    assertions: list[Assertion] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def id_must_be_unique_in_suite(cls, v: str) -> str:
        return v


# ---------------------------------------------------------------------------
# Validator results
# ---------------------------------------------------------------------------

class ValidatorFinding(BaseModel):
    rule_id: str  # HardFailRule value or custom rule name
    severity: str  # "hard" or "soft"
    passed: bool
    detail: str = ""


class ValidatorResult(BaseModel):
    findings: list[ValidatorFinding] = Field(default_factory=list)
    hard_failures: list[str] = Field(default_factory=list)
    soft_failures: list[str] = Field(default_factory=list)

    def add_finding(self, rule_id: str, severity: str, passed: bool, detail: str = "") -> None:
        finding = ValidatorFinding(rule_id=rule_id, severity=severity, passed=passed, detail=detail)
        self.findings.append(finding)
        if not passed:
            if severity == "hard":
                self.hard_failures.append(rule_id)
            else:
                self.soft_failures.append(rule_id)

    @property
    def passed(self) -> bool:
        return len(self.hard_failures) == 0


# ---------------------------------------------------------------------------
# Judge result
# ---------------------------------------------------------------------------

class JudgeResult(BaseModel):
    overall_score: float = Field(default=0.0, ge=0.0, le=1.0)
    passed: bool = True
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    failure_categories: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    diagnostics: list[SemanticJudgeDiagnostic] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Case report (v1 + v2)
# ---------------------------------------------------------------------------

class CaseStatus(str, Enum):
    passed = "passed"
    failed = "failed"
    judge_failed = "judge_failed"
    error = "error"


class CaseReport(BaseModel):
    run_id: str
    case_id: str
    module: str
    model: str
    status: CaseStatus
    hard_failures: list[str] = Field(default_factory=list)
    overall_score: float = 0.0
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    failure_categories: list[str] = Field(default_factory=list)
    agent_status: str = ""
    used_fallback: bool = False
    attempts: int = 1
    output_path: str = ""
    agent_output_path: str = ""
    agent_output: dict[str, Any] | None = None
    raw_agent_output: str | None = None
    validator_result: ValidatorResult | None = None
    judge_result: JudgeResult | None = None
    error_message: str = ""
    duration_seconds: float = 0.0
    cache_hit: bool = False
    cache_key: str = ""
    # v2 assertion results
    assertion_results: list[AssertionResult] = Field(default_factory=list)
    hard_fail_count: int = 0
    weighted_score: float = 0.0
    case_pass: bool = True
    stability: dict[str, Any] | None = None  # Multi-run stability data
    # v2.1 semantic guard
    semantic_guard: SemanticGuardReport | None = None


# ---------------------------------------------------------------------------
# Suite summary
# ---------------------------------------------------------------------------

class SuiteSummary(BaseModel):
    run_id: str
    model: str
    cases_total: int
    cases_passed: int
    cases_failed: int
    cases_judge_failed: int
    average_score: float
    hard_failure_count: int
    top_failure_categories: list[str] = Field(default_factory=list)
    module_scores: dict[str, float] = Field(default_factory=dict)
    config: RunConfig | None = None
    timestamp: str = ""
    duration_seconds: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    skipped_cases: int = 0
    # v2 assertion summary
    assertion_summary: dict[str, Any] | None = None  # Fail leaderboard, etc.
    stability_summary: dict[str, Any] | None = None  # Overall stability if multi-run


# ---------------------------------------------------------------------------
# Diff report
# ---------------------------------------------------------------------------

class DiffEntry(BaseModel):
    case_id: str
    baseline_score: float
    candidate_score: float
    score_delta: float
    baseline_hard_failures: list[str] = Field(default_factory=list)
    candidate_hard_failures: list[str] = Field(default_factory=list)
    new_hard_failures: list[str] = Field(default_factory=list)
    fixed_hard_failures: list[str] = Field(default_factory=list)
    baseline_status: str = ""
    candidate_status: str = ""
    baseline_assertion_deltas: dict[str, float] = Field(default_factory=dict)


class DiffReport(BaseModel):
    baseline_run_id: str
    candidate_run_id: str
    cases_compared: int
    average_score_delta: float
    failed_candidates: list[str] = Field(default_factory=list)
    new_hard_failures_by_case: dict[str, list[str]] = Field(default_factory=dict)
    fixed_hard_failures_by_case: dict[str, list[str]] = Field(default_factory=dict)
    entries: list[DiffEntry] = Field(default_factory=list)
    regression_passed: bool = True
    regression_notes: list[str] = Field(default_factory=list)
