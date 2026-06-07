# Diagnosis: 20260607T194202-real-d14d4a (0/49 passed, 156 hard failures)

## Commands Run

```
pfae report show output/agent-eval/20260607T194202-real-d14d4a
pfae diagnose output/agent-eval/20260607T194202-real-d14d4a
pfae run mock                                         # 49/49 passed
pfae run real --case-filter active_push_all_completed --no-sync  # 1/1 passed
```

## Root Cause

All 49 cases failed with `invalid_schema` because the agent invocation crashed before producing any output. The error messages in each case report are:

1. **`No module named 'sqlmodel'`** (majority of cases)
2. **`cannot import name 'CoordinatorAgent' from 'app.agent.coordinator'`** (remaining cases)

Both errors stem from the same root cause: **ProjectFlow's `coordinator.py` was loaded instead of the benchmark's own version.** ProjectFlow's coordinator imports `from sqlmodel import Session`, but `sqlmodel` is not a declared dependency of the benchmark (`pyproject.toml` lists only `httpx`, `pydantic`, `pydantic-settings`).

The mechanism: `app/agent_eval/cli.py` has a `_patch_app_path()` function that prepends the external ProjectFlow's `app/` directory to `app.__path__` when `--projectflow-root` is provided. After patching, `from app.agent.coordinator import CoordinatorAgent` resolves to ProjectFlow's version (which needs `sqlmodel`) instead of the benchmark's lightweight version (which does not).

Additionally, the ProjectFlow repo uses a `backend/app/` layout, not `app/` at the top level. The `_patch_app_path` function checks for `projectflow_root / "app"`, which does not exist. If the path was somehow resolved to `backend/app/`, the import chain would pull in sqlmodel-dependent code.

## Evidence

- Every case report shows `agent_status: "failed"` and `agent_output: null`
- Every case has `Error: Real mode agent invocation failed: No module named 'sqlmodel'` or the CoordinatorAgent import error
- The validator correctly reports `"Agent output is NoneType, expected dict"` (the agent never ran)
- `pfae run mock` passes 49/49 (harness and fixtures are fine)
- `pfae run real --case-filter active_push_all_completed --no-sync` passes 1/1 (benchmark's own coordinator works)
- The `.sync_meta.json` timestamp (11:55 UTC) is AFTER the run timestamp (11:42 UTC), suggesting sync was run after the failure, not before

## Classification

**Infrastructure failure** -- not an agent quality issue. The agent code never executed; the import crashed before any LLM call was made.

## Fix

The benchmark currently works correctly in its post-sync state. To prevent this from recurring:

1. **Always run `pfae sync` before `pfae run real`** (or let auto-sync handle it by providing `--projectflow-root`).

2. **If using `--projectflow-root`**, the path must point to a checkout where `app/` exists at the top level. The current ProjectFlow repo uses `backend/app/`, so the correct invocation is either:
   - `pfae run real --projectflow-root /path/to/ProjectFlow/backend` (if the code supports it), or
   - Set `PROJECTFLOW_ROOT` and let auto-sync handle the `backend/app/` resolution (the sync command already handles both layouts).

3. **The `_patch_app_path` function in `app/agent_eval/cli.py`** (line 34-52) should be updated to handle the `backend/app/` layout, similar to how `_resolve_app_dir` in `sync.py` already does. Currently it only checks `projectflow_root / "app"`, but should also check `projectflow_root / "backend" / "app"`.

## Recommendation

The run is a total infrastructure failure -- none of the 156 hard failures reflect agent quality. Discard this run. The current environment is healthy (mock 49/49, real single-case passes). Re-run with:

```bash
pfae run real
```

The auto-sync will copy the latest agent code from ProjectFlow (using the existing sync metadata), and the benchmark's own `coordinator.py` and `workflow.py` (which have no `sqlmodel` dependency) will be used for invocation.
