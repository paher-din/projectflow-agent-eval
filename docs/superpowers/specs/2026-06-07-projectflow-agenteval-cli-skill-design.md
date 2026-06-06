# ProjectFlow AgentEval CLI + Skill Design

**Date:** 2026-06-07  
**Status:** Approved design  
**Scope:** Convert ProjectFlow AgentEval into a reusable CLI + agent skill toolkit.

## Decision

ProjectFlow AgentEval will become a dedicated evaluation toolkit with two public surfaces:

1. A stable `pfae` CLI for humans and agents to run, inspect, compare, and diagnose benchmark results.
2. A `projectflow-agent-eval` skill that teaches agents when and how to call the CLI, how to interpret reports, and which safety boundaries must be preserved.

The current benchmark runner remains the execution core. The new CLI layer should orchestrate existing functionality instead of duplicating evaluation logic.

## Goals

- Make AgentEval callable from agent workflows without requiring users to remember long `python -m app.agent_eval.runner ...` commands.
- Keep the benchmark independent from the ProjectFlow product backend.
- Preserve deterministic validation as the source of hard failures.
- Make benchmark outputs easy for agents to summarize into repair-oriented feedback.
- Avoid committing generated outputs, caches, `.env`, or secrets.

## Non-Goals

- Do not imitate Feishu business features. Feishu is only a reference for the `CLI + skill` shape.
- Do not turn this repository into the main ProjectFlow backend.
- Do not introduce an MCP server or plugin package in the first version.
- Do not change real-mode provider configuration or edit `.env`.
- Do not publish the package publicly as part of this change.

## Proposed Architecture

```text
app/
  agent_eval/
    runner.py
      Core benchmark execution, comparison, reporting, and validators.
      Existing behavior should remain compatible.

    cli.py
      New top-level command entry for `pfae` and `projectflow-agent-eval`.

    commands/
      __init__.py
      cases.py
      runs.py
      reports.py
      compare.py
      diagnose.py

skills/
  projectflow-agent-eval/
    SKILL.md
    references/
      command-guide.md
      report-interpretation.md
```

`runner.py` remains the library boundary for benchmark behavior. `cli.py` owns command parsing and delegates to command modules. Command modules should be small wrappers around existing functions and report artifacts.

## CLI Surface

Expose these console scripts:

```toml
[project.scripts]
pfae = "app.agent_eval.cli:main"
projectflow-agent-eval = "app.agent_eval.cli:main"
```

### Case Commands

```powershell
pfae case list
pfae case show <case_id>
```

`case list` lists available fixture IDs. `case show` prints one fixture in a readable form, including module, entrypoint, expected behavior, forbidden behavior, minimum score, and hard fail rules.

### Run Commands

```powershell
pfae run mock
pfae run real --model deepseek-v4-pro
pfae run resume latest
pfae run retry-failed latest
pfae run retry-errors latest
```

`run mock` is the default safe command and must not require provider secrets. `run real` uses existing environment/settings configuration and must not print API keys. Resume and retry commands should resolve `latest` using the existing output directory convention.

Supported options should map to existing runner capabilities:

- `--fixtures`
- `--output-dir`
- `--model`
- `--runs-per-case`
- `--workers`
- `--judge-mode`
- `--semantic-guard`
- `--semantic-judge-model`
- `--semantic-judge-base-url`
- `--case-filter`
- `--cache-dir`
- `--no-cache`

### Report Commands

```powershell
pfae report latest
pfae report show <run_dir>
```

Report commands read existing artifacts and print a concise summary:

- run ID
- model
- pass count
- average score
- hard failure count
- top failure categories
- report directory

They should not rerun benchmarks.

### Compare Command

```powershell
pfae compare <baseline> <candidate>
```

The command delegates to the existing comparison logic and writes a diff report. It should accept `latest` where unambiguous. Regression failure should return a non-zero exit code.

### Diagnose Command

```powershell
pfae diagnose latest
pfae diagnose <run_dir>
```

`diagnose` is the most agent-oriented command. It reads case reports and summarizes:

- failed cases
- hard failures
- failed deterministic assertions
- semantic guard hard failures or uncertain findings
- failure categories
- likely repair targets by module

The output should be deterministic and evidence-backed. It must not ask an LLM to decide hard failures.

## Skill Design

Create `skills/projectflow-agent-eval/SKILL.md`.

The skill should trigger when the user asks to:

- run ProjectFlow AgentEval
- benchmark the ProjectFlow agent
- compare agent quality across runs
- inspect or diagnose benchmark failures
- rerun failed or errored cases
- produce repair guidance from AgentEval reports

The skill should instruct agents to prefer:

- `pfae run mock` for fast local checks without credentials.
- `pfae run real --model <model>` only when provider configuration already exists.
- `pfae report latest` for a quick summary.
- `pfae diagnose latest` before proposing fixes.
- `pfae compare <baseline> <candidate>` for regression checks.

The skill must preserve these boundaries:

- Do not edit `.env`, keys, tokens, or CI/CD configuration.
- Do not commit `output/`, caches, local virtual environments, or generated benchmark artifacts.
- Treat deterministic hard failures as authoritative.
- Treat LLM judge output as semantic evidence, not the sole source for hard failures.
- Keep the benchmark independent from product backend persistence.

## Data Flow

```text
User or agent request
  -> projectflow-agent-eval skill selects intent
  -> pfae command executes
  -> runner reads fixtures and invokes mock or real mode
  -> validators, assertions, semantic guard, and judge produce reports
  -> report or diagnose command summarizes artifacts
  -> agent explains result and next repair target
```

The CLI should not create product-facing state. Real mode continues to invoke the existing minimal agent runtime with `session=None`.

## Error Handling

- Missing fixture directory returns a clear non-zero error.
- Unknown case ID returns a clear non-zero error and suggests `pfae case list`.
- `latest` with no run directories returns a clear non-zero error.
- Missing real-mode provider configuration should fail clearly without printing secrets.
- Missing summary or malformed report files should identify the exact path.
- Diagnose should continue past one malformed case report when possible and report the skipped file.

## Testing Strategy

Focused tests should cover:

- CLI parser routes for `case`, `run`, `report`, `compare`, and `diagnose`.
- `latest` run resolution.
- `case show` behavior for a valid and invalid fixture ID.
- `report latest` summary extraction from fixture-like report artifacts.
- `diagnose` extraction of failed cases and hard failures.

Manual verification after implementation:

```powershell
python -m pytest -v
pfae case list
pfae run mock
pfae report latest
pfae diagnose latest
```

If comparison code is touched:

```powershell
pfae compare <baseline_run_dir> <candidate_run_dir>
```

## Acceptance Criteria

- `pfae` is available after editable install.
- `projectflow-agent-eval` remains available as a compatibility command.
- `pfae run mock` executes without credentials.
- `pfae run real --model <model>` uses existing configuration and does not print API keys.
- `pfae report latest` can locate and summarize the latest run.
- `pfae diagnose latest` produces repair-oriented, deterministic failure summaries.
- The skill lets an agent call the benchmark without reading `README.md`.
- Existing benchmark tests continue to pass.
- No generated output, caches, `.env`, API keys, or tokens are committed.

## Implementation Notes

- Prefer `argparse` unless a stronger need for another CLI framework appears. The current runner already uses `argparse`, so this avoids a new dependency.
- Keep command modules thin and testable.
- Preserve existing `app.agent_eval.runner` public functions where possible.
- Add compatibility routing so current documented command behavior keeps working during transition.
- Do not remove existing reports or output directories as part of implementation.
