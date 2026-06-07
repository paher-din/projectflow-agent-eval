# ProjectFlow AgentEval

Standalone benchmark harness for ProjectFlow agent outputs.

This repository contains the AgentEval v2 benchmark, fixtures, deterministic validators, semantic guard, LLM judge integration, reports, and the minimal ProjectFlow agent runtime needed to run the benchmark outside the main ProjectFlow application.

## What Is Included

- `app/agent_eval`: benchmark runner, fixtures, validators, assertions, semantic guard, reports
- `app/agent`: minimal agent runtime used by real-mode benchmark execution
- `app/schemas`, `app/models/enums.py`, `app/core/config.py`: minimal support types and settings
- `tests`: regression tests for benchmark behavior
- `docs/agent-evaluation-benchmark.md`: benchmark design document

## What Is Not Included

- real `.env` files or API keys
- benchmark output directories
- database models and backend service code
- ProjectFlow web/frontend code

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env` locally with your provider keys. Do not commit `.env`.

## CLI Toolkit

After editable install, use the short CLI:

```powershell
pfae case list
pfae run mock
pfae report latest
pfae diagnose latest
```

The compatibility command is also available:

```powershell
projectflow-agent-eval run mock
```

The lower-level runner module remains available for direct development use, but agents should prefer `pfae`.

## Run Offline Benchmark

```powershell
.\.venv\Scripts\python -m app.agent_eval.runner run --mode mock --fixtures app\agent_eval\fixtures --output-dir output\agent-eval-smoke --model stub
```

## Run Real LLM Benchmark

```powershell
.\.venv\Scripts\python -m app.agent_eval.runner run --mode real --fixtures app\agent_eval\fixtures --output-dir output\agent-eval-real --model deepseek-v4-pro --semantic-guard auto --semantic-judge-model deepseek-v4-flash
```

## Run Tests

```powershell
.\.venv\Scripts\python -m pytest -v
```

## Maintenance Boundary

This repository is maintained as a standalone benchmark tool. Changes to ProjectFlow product behavior should live in the main ProjectFlow repository. Changes to benchmark fixtures, assertions, judge parsing, reporting, or benchmark runtime should live here.

