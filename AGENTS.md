# AGENTS.md

## Communication

- Default to Chinese for user-facing discussion.
- Keep code, commands, paths, and identifiers in English.
- State conclusions first, then reasoning.

## Engineering Rules

- Keep the benchmark independent from the ProjectFlow product backend.
- Do not commit `.env`, API keys, tokens, benchmark output directories, caches, or local virtual environments.
- Run focused tests after benchmark logic changes.
- Prefer deterministic validation over LLM judge decisions for schema, IDs, dates, dependency graphs, and persistence safety.
- LLM judge may evaluate semantic quality, but must not be the sole source of hard failures for deterministic facts.

## Public Repository Safety

- Treat this repository as public.
- Before committing or pushing, run a secret scan over tracked candidate files.
- Keep `.env.example` placeholder-only.

