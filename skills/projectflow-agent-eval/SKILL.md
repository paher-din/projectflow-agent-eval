---
name: projectflow-agent-eval
description: Use when running, inspecting, comparing, or diagnosing ProjectFlow AgentEval benchmark results through the `pfae` CLI.
---

# ProjectFlow AgentEval

Use this skill when the user asks to run ProjectFlow AgentEval, benchmark the ProjectFlow agent, compare quality across runs, inspect failures, rerun failed cases, or turn AgentEval reports into repair guidance.

## First Steps

1. Prefer `pfae run mock` for fast local checks that do not need provider credentials.
2. Use `pfae run real --model <model>` only when the environment is already configured.
3. Use `pfae report latest` for a concise run summary.
4. Use `pfae diagnose latest` before proposing fixes for benchmark failures.
5. Use `pfae compare <baseline> <candidate>` for regression checks.

## Real-Mode Setup

When real mode lacks provider configuration, run `pfae config init`. Do not ask the user to put keys in `.env` unless they explicitly prefer that. Use `pfae config show` to confirm configured model names; never display full API keys.

Agent and judge models are managed as separate named registries. Do not use `config judge ...` commands to manage Agent models or `config agent ...` commands to manage Judge models. The two registries are independent:

- `pfae config agent add <name>` / `pfae config agent use <name>` / `pfae config agent list` / `pfae config agent show <name>`
- `pfae config judge add <name>` / `pfae config judge use <name>` / `pfae config judge list` / `pfae config judge show <name>`

## Safety Boundaries

- Do not edit `.env`, keys, tokens, CI/CD configuration, or provider credentials.
- Do not commit `output/`, caches, local virtual environments, or generated benchmark artifacts.
- Treat deterministic hard failures as authoritative.
- Treat LLM judge output as semantic evidence, not the sole source of hard failures.
- Keep this benchmark independent from ProjectFlow product backend persistence.

## References

- Read `references/command-guide.md` for exact command shapes.
- Read `references/report-interpretation.md` when explaining failures.
