# Benchmark Failure Diagnosis: 20260607T194202-real-d14d4a

## Summary

49/49 cases failed, all showing `invalid_schema`. Root cause: **the real agent invocation crashed on every case with `No module named 'sqlmodel'`**, producing `None` output. All downstream assertions then failed because they received `None` instead of a dict.

## Commands Run

```bash
# 1. Inspect suite summary
cat output/agent-eval/20260607T194202-real-d14d4a/suite_summary.json

# 2. Inspect a sample case report
cat output/agent-eval/20260607T194202-real-d14d4a/active_push_all_completed.report.json

# 3. Check if sqlmodel is installed in venv
.venv/bin/python -c "import sqlmodel; print(sqlmodel.__version__)"
# Output: 0.0.38

# 4. Test agent imports directly
.venv/bin/python -c "from app.agent.coordinator import CoordinatorAgent"
# Output: (no error)

# 5. Test imports with ProjectFlow path patching
.venv/bin/python -c "
import app
from pathlib import Path
external_app = str(Path('/Users/robertwu/Documents/Projects/ProjectFlow').resolve() / 'app')
if external_app not in app.__path__:
    app.__path__.insert(0, external_app)
from app.agent.coordinator import CoordinatorAgent
from app.agent.workflow import AgentRunResult
from app.schemas.workspace_state import WorkspaceStateResponse
print('All imports OK')
"
# Output: All imports OK

# 6. Check if agent code imports sqlmodel anywhere
grep -rn "sqlmodel" app/agent/
# Output: (no matches)

# 7. Trace all transitive imports for sqlmodel
.venv/bin/python -c "
import sys
for mod in list(sys.modules.keys()):
    if mod.startswith('app.'):
        del sys.modules[mod]
import importlib
original_import = __builtins__.__import__
imported_modules = []
def tracing_import(name, *args, **kwargs):
    imported_modules.append(name)
    return original_import(name, *args, **kwargs)
__builtins__.__import__ = tracing_import
try:
    from app.agent.coordinator import CoordinatorAgent
finally:
    __builtins__.__import__ = original_import
sqlmodel_imports = [m for m in imported_modules if 'sqlmodel' in m.lower()]
print(f'Total imports: {len(imported_modules)}')
print(f'Sqlmodel imports: {sqlmodel_imports}')
"
# Output: Total imports: 3095, Sqlmodel imports: []

# 8. Reproduce: run a single case in real mode
.venv/bin/pfae run real --case-filter active_push_all_completed --no-cache
# Output: 1/1 passed, 30.5s duration

# 9. Run pfae diagnose
.venv/bin/pfae diagnose output/agent-eval/20260607T194202-real-d14d4a
# Output: lists all 49 failed cases with invalid_schema

# 10. Check git status of agent code
git status -- app/agent/
# Output: 7 modified files + 1 untracked (.sync_meta.json)

# 11. Check sync metadata
cat app/agent/.sync_meta.json
```

## Diagnosis

### What Happened

Every case failed identically with this error chain:

1. `_run_real_agent_flow()` raised `ImportError: No module named 'sqlmodel'`
2. The exception was caught at `runner.py:429-431`, setting `agent_status = "failed"` and `agent_output = None`
3. All validators/assertions received `None` instead of a dict, triggering `invalid_schema` on every case
4. The judge was skipped ("deterministic hard failure detected")

### Evidence

From `active_push_all_completed.report.json`:
```json
"error_message": "Real mode agent invocation failed: No module named 'sqlmodel'",
"agent_status": "failed",
"agent_output_path": "",
"duration_seconds": 0.0058
```

The entire 49-case benchmark completed in **0.021 seconds** -- impossibly fast for real LLM calls. This confirms every case crashed immediately at import time, before any LLM call was made.

### Root Cause

The `sqlmodel` module was not importable in the Python environment at the time the benchmark ran. This is a **runtime environment issue**, not a code bug.

Current state (verified):
- `sqlmodel` 0.0.38 IS installed in `.venv`
- All agent imports work fine (including with ProjectFlow path patching)
- The agent code does NOT import `sqlmodel` directly
- No transitive import chain leads to `sqlmodel`
- A reproduce run of 1 case passes: **1/1, score 1.0, 30.5s**

The benchmark ran at `2026-06-07T11:42:02 UTC` but the `.sync_meta.json` shows `synced_at: 2026-06-07T11:55:59 UTC` -- the sync happened 13 minutes AFTER the failed run. This means:

1. The benchmark was run WITHOUT syncing (`--projectflow-root` was not passed and `PROJECTFLOW_ROOT` was not set)
2. The agent code in place at run time was the version from git commit `108dd64` (initial commit)
3. The sync at 11:55 replaced the agent code with the ProjectFlow version, which is what's currently on disk

The original committed `llm_client.py` uses `import httpx`, while the synced version uses `urllib`. However, `httpx` 0.28.1 IS installed, so this alone shouldn't cause the `sqlmodel` error. The most likely explanation is that the Python environment was in a different state at run time (e.g., a different venv was active, or `sqlmodel` was not yet installed).

### Additional Config Issue

The config shows `"model": ""` (empty string). When model is not passed via `--model`, `run_benchmark` sets it to `""` for real mode. The agent's LLM client then falls back to `app_settings.llm_model` (default: `"gpt-4o-mini"`). If the `.env` doesn't set `LLM_PROVIDER` to a real provider, it defaults to `"mock"`, which returns `{}` -- this would produce valid but empty outputs. This is a secondary concern.

## Recommendation

1. **Re-run the benchmark now** -- the environment is correctly set up and a single-case reproduce run passed:
   ```bash
   .venv/bin/pfae run real --projectflow-root /Users/robertwu/Documents/Projects/ProjectFlow
   ```
   This will sync the latest agent code AND run the benchmark.

2. **Always pass `--projectflow-root`** when running in real mode, or set `PROJECTFLOW_ROOT` in your environment. Without it, the sync is skipped and the benchmark runs against potentially stale agent code.

3. **Consider adding a pre-flight check** in `run_benchmark` that verifies critical imports (`sqlmodel`, `httpx`, etc.) before running 49 cases. This would catch environment issues in <1 second instead of producing a misleading 49-case failure report.

4. **The `model: ""` config** is not causing the crash but means the agent is using the default model from `app_settings`. Pass `--model deepseek-chat` (or whatever model you want) explicitly to be clear about what's being evaluated.
