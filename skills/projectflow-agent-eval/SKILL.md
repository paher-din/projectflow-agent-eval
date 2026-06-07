---
name: projectflow-agent-eval
description: Use this skill whenever an agent needs to operate the standalone ProjectFlow AgentEval harness with the `pfae` CLI. Trigger for requests to benchmark or test ProjectFlow agent outputs, run mock or real AgentEval, configure first-run real LLM access, add or switch separate Agent and Judge model registries, inspect cases, read reports, diagnose failures, retry failed or errored cases, or compare benchmark runs. Prefer this over direct runner-module commands.
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
| Real model benchmark | Ensure config, then run `pfae run real` |
| First-time real setup | Run `pfae config init` |
| Add or switch evaluated agent model | Use `pfae config agent ...` |
| Add or switch auxiliary judge model | Use `pfae config judge ...` |
| Inspect available benchmark cases | Use `pfae case list` or `pfae case show <case_id>` |
| Explain a run result | Use `pfae report latest` or `pfae report show <run_dir>` |
| Find likely repair targets | Use `pfae diagnose latest` before recommending fixes |
| Compare quality across two runs | Use `pfae compare <baseline> <candidate>` |

Read `references/command-guide.md` when you need exact flags or command shapes.
Read `references/report-interpretation.md` before explaining failures or turning
reports into repair guidance.

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
2. For real LLM checks, run `pfae config show` first when useful, then `pfae run real`.
3. For a focused rerun, add `--case-filter <case_id>` if the user names cases.
4. For flaky or stability-sensitive behavior, use `--runs-per-case <n>`.
5. After a failed run, run `pfae diagnose latest` before proposing code or prompt changes.

Summaries should include the run ID, report directory, pass count, hard failures,
and the smallest likely repair target. Do not paste entire raw model outputs
unless the user asks and you have checked for sensitive content.

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
