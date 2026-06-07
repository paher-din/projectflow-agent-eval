# ProjectFlow AgentEval

Standalone benchmark harness for testing ProjectFlow agent outputs.

This repository packages the ProjectFlow AgentEval benchmark as a CLI plus an agent skill. It is designed to be downloaded, installed, and called from an agent workflow without depending on the main ProjectFlow backend.

## What This Tool Does

ProjectFlow AgentEval runs fixture-based benchmark cases against ProjectFlow agent behavior and produces structured reports for quality, safety, and regression checks.

It includes:

- `pfae`: the primary CLI for agents and humans
- `app/agent_eval`: benchmark runner, fixtures, validators, assertions, reports, semantic guard, and LLM judge integration
- `app/agent`: a minimal ProjectFlow agent runtime used by real-mode benchmark execution
- `skills/projectflow-agent-eval`: the agent skill that tells Codex or another agent when and how to call `pfae`
- `tests`: regression tests for the benchmark harness
- `docs/agent-evaluation-benchmark.md`: benchmark design notes

It intentionally excludes:

- real `.env` files, API keys, or tokens
- benchmark output directories and caches
- database models and production backend services
- ProjectFlow web or frontend code

## Install

From a fresh clone:

```powershell
python -m pip install -e ".[dev]"
pfae --help
```

The compatibility entrypoint is also available:

```powershell
projectflow-agent-eval --help
```

Agents should prefer `pfae` over direct `python -m app.agent_eval.runner` commands.

## Quick Start

Run a fast local benchmark that does not need real LLM credentials:

```powershell
pfae run mock
pfae report latest
pfae diagnose latest
```

Use `mock` for smoke checks, CLI validation, report parsing, and benchmark harness changes. It is the safest default when no real provider configuration is available.

## First Real-Mode Setup

Real mode evaluates the ProjectFlow agent with a real LLM and can also use an auxiliary Judge model for semantic checks.

On first use, run:

```powershell
pfae config init
```

The wizard asks for two separate model entries:

1. Agent model: `name`, `base_url`, `api_key`, `model`
2. Judge model: `name`, `base_url`, `api_key`, `model`

The config is stored outside this repository in your user config directory. API keys are never printed by `pfae config show`.

```powershell
pfae config path
pfae config show
```

You can also start real mode directly; if no real config exists, `pfae run real` starts the same first-run setup:

```powershell
pfae run real
```

## Model Registry

Agent and Judge models are managed as separate registries. Do not mix them.

Agent models are the models being evaluated:

```powershell
pfae config agent add deepseek-pro
pfae config agent use deepseek-pro
pfae config agent list
pfae config agent show deepseek-pro
```

Judge models are auxiliary semantic evaluators:

```powershell
pfae config judge add deepseek-flash
pfae config judge use deepseek-flash
pfae config judge list
pfae config judge show deepseek-flash
```

`pfae config agent add` and `pfae config judge add` require an existing first-run config from `pfae config init`. After switching, `pfae run real` uses the current Agent model for `LLM_*` settings and the current Judge model for `SEMANTIC_JUDGE_*` settings.

`--model` is mainly a run/report label and cache key. Use `pfae config agent use <name>` and `pfae config judge use <name>` to switch real providers.

## Run Benchmarks

Run all mock cases:

```powershell
pfae run mock
```

Run all real cases with the current Agent and Judge config:

```powershell
pfae run real
```

Run selected cases:

```powershell
pfae run mock --case-filter clarify_sparse_project
pfae run real --case-filter clarify_sparse_project
```

Run repeated attempts for stability checks:

```powershell
pfae run real --case-filter clarify_sparse_project --runs-per-case 3
```

Resume or retry from a previous run:

```powershell
pfae run resume latest
pfae run retry-failed latest
pfae run retry-errors latest
```

Useful flags:

- `--case-filter <case_id[,case_id]>`: run selected cases only
- `--runs-per-case <n>`: repeat each selected case for stability checks
- `--workers <n>`: control concurrency
- `--judge-mode auto|llm|stub`: select main judge behavior
- `--semantic-guard off|auto|required`: control semantic guard strictness
- `--no-cache`: force fresh real LLM calls

## Inspect Cases

```powershell
pfae case list
pfae case show <case_id>
```

Use these before adding or modifying benchmark fixtures.

## Reports And Diagnosis

Read the latest run:

```powershell
pfae report latest
```

Read a specific run directory:

```powershell
pfae report show <run_dir>
```

Diagnose likely repair targets:

```powershell
pfae diagnose latest
```

Compare two runs:

```powershell
pfae compare <baseline_run_dir> <candidate_run_dir>
```

A non-zero `compare` exit code means the candidate failed the regression gate.

When interpreting failures, prioritize deterministic hard failures, failed hard assertions, semantic guard hard failures with evidence, repeated failure categories, then low semantic judge scores. A high average score does not make a run healthy if hard failures exist.

## Agent Skill Usage

The bundled skill lives at:

```text
skills/projectflow-agent-eval/SKILL.md
```

Use this skill when an agent needs to:

- run ProjectFlow AgentEval
- configure real Agent and Judge models
- switch model registries
- inspect benchmark cases
- read or diagnose reports
- retry failed cases
- compare benchmark runs

The skill uses progressive disclosure:

- `SKILL.md`: routing rules, safety boundaries, and default workflow
- `references/command-guide.md`: exact command shapes
- `references/report-interpretation.md`: failure interpretation rules

## Run Tests

```powershell
python -m pytest -v
```

For CLI or config changes, also run:

```powershell
python -m ruff check app/agent_eval/cli.py app/agent_eval/commands tests/test_agent_eval_cli.py tests/test_agent_eval_config.py
```

## Safety And Maintenance

- Keep real API keys, tokens, passwords, and `.env` files out of the repository.
- Do not commit `output/`, caches, local virtual environments, or generated benchmark artifacts.
- Treat this repository as public.
- Keep the benchmark independent from ProjectFlow product backend persistence.
- Put benchmark fixtures, validators, judge parsing, report writing, CLI behavior, and skill docs here.
- Put production ProjectFlow product changes in the main ProjectFlow repository.
