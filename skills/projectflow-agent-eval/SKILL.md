---
name: projectflow-agent-eval
description: Operate the ProjectFlow AgentEval benchmark harness (`pfae` CLI). Use when the user wants to run benchmarks (mock or real), sync agent code from ProjectFlow, diagnose benchmark failures, compare runs across versions, or configure LLM models for evaluation. Trigger on mentions of "benchmark", "eval", "pfae", "agent quality", or ProjectFlow performance testing.
compatibility: Requires the `pfae` CLI installed from this repository. Real mode needs user-level model config from `pfae config init` or equivalent environment variables.
---

# ProjectFlow AgentEval

ProjectFlow AgentEval is a standalone benchmark harness for testing ProjectFlow
agent outputs. Treat `pfae` as the primary interaction surface. Use lower-level
Python runner commands only when maintaining the benchmark internals.

## Decide the Workflow

Map the user's request to one of these paths:

| User intent | Default action |
| --- | --- |
| "Quick check", "does the harness work", no credentials | Run `pfae run mock` |
| Real model benchmark | Sync agent code, then run `pfae run real` |
| First-time real setup | Run `pfae config init` |
| Sync agent code from ProjectFlow | Run `pfae sync` |
| Add or switch evaluated agent model | Use `pfae config agent ...` |
| Add or switch auxiliary judge model | Use `pfae config judge ...` |
| Inspect available benchmark cases | Use `pfae case list` or `pfae case show <case_id>` |
| Explain a run result | Use `pfae report latest` or `pfae report show <run_dir>` |
| Find likely repair targets | Use `pfae diagnose latest` before recommending fixes |
| Compare quality across two runs | Use `pfae compare <baseline> <candidate>` |

Read `references/command-guide.md` when you need exact flags or command shapes.
Read `references/report-interpretation.md` before explaining failures or turning
reports into repair guidance.

## Sync Agent Code

The benchmark evaluates ProjectFlow's agent modules. To keep the benchmark in
sync with the current ProjectFlow codebase, use `pfae sync` before running real
benchmarks.

`pfae sync` copies selected agent files from the ProjectFlow working directory
into the benchmark. Uncommitted local changes are included — useful for testing
optimizations before committing.

```
pfae sync --projectflow-root /path/to/ProjectFlow
```

Or set the environment variable once:
```
export PROJECTFLOW_ROOT=/path/to/ProjectFlow
pfae sync
```

### What Gets Synced

Only the files that contain agent logic — prompts, output schemas, LLM client,
and the 9 agent modules:

- `app/agent/llm_client.py` — LLM client (OpenAI-compatible HTTP calls)
- `app/agent/output_schemas.py` — Pydantic models for agent output validation
- `app/agent/prompts.py` — system prompts and prompt construction
- `app/agent/modules/` — the 9 agent modules (clarification, planning, etc.)

### What Does NOT Get Synced

The benchmark keeps its own versions of these files:

- `app/agent/coordinator.py` — benchmark version has no `sqlmodel` dependency
- `app/agent/workflow.py` — benchmark version has no database logging
- `app/schemas/workspace_state.py` — fixtures depend on its schema; syncing it
  breaks fixture validation (new required fields like `owner_user_id`, `can_cut`)
- `app/core/config.py` — benchmark has `semantic_judge_*` fields the project lacks
- `app/agent_eval/` — all fixtures, validators, assertion rules

### Why This Scope Matters

ProjectFlow's `coordinator.py` and `workflow.py` import `sqlmodel.Session` for
database persistence. The benchmark doesn't need or have `sqlmodel`. Syncing
these files would cause `ImportError: No module named 'sqlmodel'`.

Similarly, `workspace_state.py` defines the **input** schema for fixture data.
When ProjectFlow adds new required fields (e.g., `owner_user_id`, `can_cut`),
the fixtures must be updated to include them. Syncing the schema alone without
updating fixtures causes `ValidationError` on every case.

After sync, `.sync_meta.json` records the git commit, dirty state, and timestamp.
When `pfae run real` is called, auto-sync runs first by default. Use `--no-sync`
to skip (e.g., for debugging with previously synced code).

## Real-Mode Setup

When real mode lacks provider configuration, run `pfae config init`. The first
setup prompts for one Agent model and one Judge model. These are stored in a
user-level config file outside the repository.

After first setup, Agent and Judge models are managed as separate named
registries. Keep the roles separate:

- `pfae config agent add <name>` / `pfae config agent use <name>` / `pfae config agent list` / `pfae config agent show <name>`
- `pfae config judge add <name>` / `pfae config judge use <name>` / `pfae config judge list` / `pfae config judge show <name>`

Use `agent` commands only for the evaluated ProjectFlow agent model. Use `judge`
commands only for auxiliary semantic judge models. Do not use `--model` as the
normal way to switch providers; in this harness it is mainly a run/report label
and cache key. Switch the active model with `pfae config agent use <name>` or
`pfae config judge use <name>`.

Use `pfae config show` to confirm the current Agent and Judge entries. It masks
API keys; never print full keys.

## Running Benchmarks

Prefer the smallest run that answers the user:

1. For local sanity checks, run `pfae run mock`.
2. For real LLM checks, ensure agent code is synced, then run `pfae run real`.
3. For a focused rerun, add `--case-filter <case_id>` if the user names cases.
4. For flaky or stability-sensitive behavior, use `--runs-per-case <n>`.
5. After a failed run, run `pfae diagnose latest` before proposing code or prompt changes.

### Diagnosing Failures

When a real benchmark run has failures, classify them before suggesting fixes.
Do not analyze internal CLI code (`cli.py`, `_patch_app_path`, etc.) — focus on
the user-facing commands and their output.

**Quick triage flow** (follow this order):

1. Run `pfae diagnose latest` to see failure categories
2. If most cases show `invalid_schema` or `agent_status: "failed"`:
   - This is an **infrastructure failure**, not an agent quality issue
   - Run `pfae run mock` — if mock passes, the harness and fixtures are fine
   - Fix: `pfae run real` (auto-syncs agent code before running)
   - Do NOT suggest code changes or prompt edits for infrastructure failures
3. If cases pass schema but score low on quality dimensions:
   - These are **real quality failures** worth investigating
   - Categories like `scope_creep`, `weak_actionability`, `no_op_replan`,
     `dependency_inconsistency` indicate agent logic or prompt issues

**Schema failures** (`invalid_schema` in hard failures):
The agent output doesn't match the expected JSON structure. Common causes:
- Agent code is outdated → fix: `pfae run real` (auto-syncs)
- LLM is hallucinating field names → fix: adjust agent prompts

**Fixture/validator failures** (`Field required` errors before agent runs):
The fixture data doesn't match `WorkspaceStateResponse` schema. This means
ProjectFlow's input schema changed and fixtures need updating. Run `pfae run mock`
to verify — if mock passes, fixtures are fine and the issue is elsewhere.

**Real quality failures** (no schema issues, agent runs but scores low):
These are genuine agent behavior problems worth reporting to the user.

### Version Tracking

Each real benchmark run records which ProjectFlow version was tested:
- Git commit hash from the ProjectFlow repo
- Whether the working directory had uncommitted changes (dirty state)
- The source path of the ProjectFlow checkout

When comparing runs from different ProjectFlow versions, `pfae compare` shows
the version difference at the top of the diff report. This helps correlate
score changes with code changes.

### Typical Development Workflow

```bash
# 1. Make changes to ProjectFlow agent code
# 2. Run benchmark to check impact (auto-syncs first)
pfae run real

# 3. Compare with previous results
pfae compare <previous-run> latest

# 4. If satisfied, commit ProjectFlow changes
# 5. Run again to get a clean (non-dirty) baseline
pfae run real
```

## Safety Boundaries

- Do not edit `.env`, keys, tokens, CI/CD configuration, or provider credentials.
- Do not commit `output/`, caches, local virtual environments, or generated benchmark artifacts.
- Do not run `pfae config init` with invented or placeholder credentials.
- Treat deterministic hard failures as authoritative.
- Treat LLM judge output as semantic evidence, not the sole source of hard failures.
- Keep this benchmark independent from ProjectFlow product backend persistence.

## References

- `references/command-guide.md`: exact command shapes and common flows.
- `references/report-interpretation.md`: failure priority and response format.
