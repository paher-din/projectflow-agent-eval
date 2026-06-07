# Report Interpretation

Prioritize failures in this order:

1. Deterministic hard failures.
2. Failed hard assertions.
3. Semantic guard hard failures with evidence.
4. Repeated failure categories across cases.
5. Low semantic judge scores.

Do not mark a run healthy because the average score is high if any hard failure exists.

## Summary Format

When summarizing a failed or partially failed run, include:

- case ID
- module
- hard failures
- failed assertions
- failure categories
- report directory
- the smallest likely repair target

Keep the repair target narrow. Prefer "fix the validator expectation", "adjust
the fixture workspace state", "repair the agent output for module X", or "rerun
case Y with real mode" over broad project refactors.

## Classifying Failures

Before recommending code or prompt changes, classify each failure.
Do not analyze internal CLI source code — focus on commands and output.

**Quick triage** (follow this order):
1. If most cases show `invalid_schema` or `agent_status: "failed"` → infrastructure failure
2. Run `pfae run mock` — if mock passes, harness and fixtures are fine
3. Fix: `pfae run real` (auto-syncs). Do NOT suggest code changes.

**Infrastructure failures** (not agent quality issues):
- `invalid_schema` + `Agent output is NoneType` — agent invocation crashed
- `invalid_schema` + `Field required` on `WorkspaceStateResponse` — fixture mismatch
- `empty_fallback` — agent hit an error and fell back to minimal output

**Quality failures** (these are the real findings):
- `scope_creep` — agent suggests work outside the project scope
- `weak_actionability` — suggestions aren't concrete enough
- `no_op_replan` — agent doesn't make meaningful changes when it should
- `dependency_inconsistency` — ordering without dependency declarations
- `immutable_state_violation` — agent tries to modify completed/accepted state
- `date_time_error` — date logic mistakes
- `hallucinated_entity` — agent invents team members or tasks that don't exist

Only suggest agent code/prompt changes for quality failures.

## What Counts as Strong Evidence

Treat these as strong evidence:

- deterministic assertion failures
- schema or JSON contract failures
- entity, date, dependency, persistence, or MVP-boundary violations
- repeated failure categories across multiple cases
- semantic guard hard failures with concrete evidence

Treat these as weaker evidence:

- low LLM judge scores without a matching deterministic or semantic finding
- single-run instability when `--runs-per-case` was not used
- judge parser errors or unavailable judge diagnostics

## Recommended Response Shape

For a concise diagnosis, use this shape:

```text
Run: <run_id or run_dir>
Status: <passed>/<total> cases passed, <hard_failure_count> hard failures
Main issue: <one sentence>
Evidence: <case_id> / <assertion or hard failure>
Repair target: <smallest likely code, fixture, or prompt area>
Next command: <one pfae command if useful>
```

Do not quote secrets or dump full raw model outputs unless the user explicitly asks and the content has been checked for sensitive values.
