# ProjectFlow AgentEval Command Guide

Use these commands from the repository root after the package has been installed
in editable mode. Prefer `pfae` over direct `python -m app.agent_eval.runner`
unless you are maintaining internals.

## Sync Agent Code

```bash
# Sync from explicit path
pfae sync --projectflow-root /path/to/ProjectFlow

# Sync using environment variable
export PROJECTFLOW_ROOT=/path/to/ProjectFlow
pfae sync

# View sync metadata
cat app/agent/.sync_meta.json
```

`pfae sync` copies selected agent files from the ProjectFlow working directory:
`llm_client.py`, `output_schemas.py`, `prompts.py`, and `modules/`. It does NOT
sync `coordinator.py`, `workflow.py` (they depend on `sqlmodel`), or
`workspace_state.py` (fixtures depend on its schema). Uncommitted changes are
included. The sync metadata records the git commit, dirty state, and timestamp.

If real benchmark shows `invalid_schema` on all cases, check:
1. Is agent code synced? (`pfae sync`)
2. Are fixtures aligned with current schema? (run `pfae run mock` — if mock passes, schema is fine)

## Inspect Cases

```bash
pfae case list
pfae case show <case_id>
```

## Run Benchmark

```bash
pfae run mock
pfae run real
pfae run mock --case-filter clarify_sparse_project
pfae run real --case-filter clarify_sparse_project --runs-per-case 3
pfae run resume latest
pfae run retry-failed latest
pfae run retry-errors latest
```

Use `mock` when credentials are unavailable or the user only wants a local sanity check.
Use `real` when the user wants to evaluate actual LLM behavior. `pfae run real`
loads the current Agent and Judge model entries from user config when environment
variables are not already set. Auto-sync runs before real mode by default.

Useful flags:

- `--case-filter <case_id[,case_id]>`: run only selected cases.
- `--runs-per-case <n>`: run repeated attempts for stability checks.
- `--workers <n>`: control concurrency.
- `--judge-mode auto|llm|stub`: select main judge behavior.
- `--semantic-guard off|auto|required`: control semantic guard strictness.
- `--no-cache`: force new real LLM calls.
- `--model <label>`: reporting/cache label; do not rely on it for provider switching.
- `--projectflow-root <path>`: set the ProjectFlow checkout path (also `PROJECTFLOW_ROOT` env var).
- `--sync` / `--no-sync`: enable/disable auto-sync before real runs (default: enabled).

## Configure Real Models

```bash
pfae config path
pfae config init
pfae config show
```

First-time setup uses `pfae config init`. It prompts for:

1. Agent model name, base URL, API key, model
2. Judge model name, base URL, API key, model

After first setup, Agent and Judge models are managed as separate registries:

```bash
pfae config agent add <name>
pfae config agent use <name>
pfae config agent list
pfae config agent show <name>

pfae config judge add <name>
pfae config judge use <name>
pfae config judge list
pfae config judge show <name>
```

Do not use `config judge ...` commands to manage Agent models or `config agent ...` commands to manage Judge models.
`pfae config agent add <name>` and `pfae config judge add <name>` require an
existing config from `pfae config init`; they are for adding more entries after
first setup.

`pfae run real` starts setup automatically when no environment or user config exists.
If the user explicitly asks where credentials are stored, show `pfae config path`.
Do not print full API keys.

## Read Reports

```bash
# View all run history (auto-appended after each run)
cat output/agent-eval/HISTORY.md

pfae report latest
pfae report show <run_dir>
pfae diagnose latest
```

Run `diagnose` before recommending code or prompt changes.

## Compare Runs

```bash
pfae compare <baseline_run_dir> <candidate_run_dir>
```

A non-zero exit code means the candidate failed the regression gate.
When the two runs used different ProjectFlow versions, the diff report shows
the commit hash and dirty state for each run.

## Common Flows

Quick local sanity check:

```bash
pfae run mock
pfae report latest
```

First real benchmark:

```bash
pfae config init
pfae config show
pfae run real          # auto-syncs from PROJECTFLOW_ROOT first
pfae diagnose latest
```

Test local ProjectFlow optimization (uncommitted changes):

```bash
# After making changes in ProjectFlow directory:
pfae run real          # auto-syncs working directory, records dirty state
pfae compare <previous-run> latest
```

Sync without running:

```bash
pfae sync
```

Switch the evaluated agent model:

```bash
pfae config agent list
pfae config agent use <name>
pfae run real
```

Switch the auxiliary judge model:

```bash
pfae config judge list
pfae config judge use <name>
pfae run real
```
