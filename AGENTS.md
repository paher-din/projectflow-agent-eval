# AGENTS.md

## Project Overview

This is a standalone AgentEval benchmark harness for ProjectFlow agent outputs. The primary agent interaction surface is the `pfae` CLI (see README.md for human-oriented docs).

## Communication

- Default to Chinese for user-facing discussion.
- Keep code, commands, paths, and identifiers in English.
- State conclusions first, then reasoning.

## Documentation Map

| Target | File | Audience |
|--------|------|----------|
| Agent skill | `skills/projectflow-agent-eval/SKILL.md` | Agents — when and how to use the `pfae` CLI |
| Command reference | `skills/projectflow-agent-eval/references/command-guide.md` | Agents — command shapes |
| Report guide | `skills/projectflow-agent-eval/references/report-interpretation.md` | Agents — failure interpretation |
| Benchmark design | `docs/agent-evaluation-benchmark.md` | Humans and agents — v2 assertion-based spec |
| User readme | `README.md` | Humans — setup and quick start |

## Engineering Rules

- Keep the benchmark independent from the ProjectFlow product backend.
- Do not commit `.env`, API keys, tokens, benchmark output directories, caches, or local virtual environments.
- Run focused tests after benchmark logic changes: `python -m pytest tests/ -v`
- Prefer deterministic validation over LLM judge decisions for schema, IDs, dates, dependency graphs, and persistence safety.
- LLM judge may evaluate semantic quality, but must not be the sole source of hard failures for deterministic facts.
- When asked to run the benchmark, prefer `pfae run mock` for fast local checks; use `pfae run real` only with existing provider config. The `--model` flag on `pfae run` is a reporting/cache label — switch the active model via `pfae config agent use <name>` or `pfae config judge use <name>` instead.
- For real mode testing against the main ProjectFlow Agent code (not this repo's snapshot), use `--projectflow-root <path>` or set `PROJECTFLOW_ROOT`. This makes `app.agent.*` imports resolve to the external checkout via `app.__path__` extension. The run metadata records the source path and git commit.
- The benchmark suite has 43 cases across 10 modules (4-5 per module), including 8 warm-state fixtures that test Agent behavior with accumulated workspace state (multiple cycles, existing tasks, rejected proposals). Mock mode passes all 43; real mode results depend on Agent quality.

## Public Repository Safety

- Treat this repository as public.
- Before committing or pushing, run a secret scan over tracked candidate files.
- Keep `.env.example` placeholder-only.

