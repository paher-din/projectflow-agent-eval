# ProjectFlow AgentEval Separated Model Registry Design

**Date:** 2026-06-07  
**Status:** Approved design  
**Scope:** Add independent Agent and Judge model registries with add/use/list/show commands.

## Decision

ProjectFlow AgentEval should not treat an Agent model and a Judge model as one bundled profile. The two roles serve different purposes and must be managed independently:

- Agent models are evaluated by the benchmark.
- Judge models assist semantic evaluation.

The user-level config will become two separate named registries:

```text
agent_models
judge_models
current_agent
current_judge
```

`pfae run real` will use `current_agent` for `LLM_*` values and `current_judge` for `SEMANTIC_JUDGE_*` values.

## Goals

- Keep Agent and Judge model entries separate so they cannot be accidentally mixed.
- Allow first-time setup to collect one Agent model and one Judge model in one guided flow.
- Allow later additions to only one side:
  - `pfae config agent add <name>`
  - `pfae config judge add <name>`
- Allow independent switching:
  - `pfae config agent use <name>`
  - `pfae config judge use <name>`
- Keep API keys masked in display output.
- Preserve backward compatibility with the current single-pair config shape.

## Non-Goals

- Do not create bundled profiles that switch Agent and Judge together.
- Do not allow Judge entries to be selected as Agent entries, or Agent entries to be selected as Judge entries.
- Do not modify `.env`.
- Do not encrypt keys in this iteration.
- Do not add provider-specific validation or model discovery.

## Config Shape

New shape:

```json
{
  "current_agent": "deepseek-pro",
  "current_judge": "deepseek-flash",
  "agent_models": {
    "deepseek-pro": {
      "base_url": "https://api.deepseek.com",
      "api_key": "agent-key",
      "model": "deepseek-v4-pro"
    }
  },
  "judge_models": {
    "deepseek-flash": {
      "base_url": "https://api.deepseek.com",
      "api_key": "judge-key",
      "model": "deepseek-v4-flash"
    }
  }
}
```

Backward compatibility:

```json
{
  "agent": {},
  "judge": {}
}
```

will load as:

```text
current_agent = "default-agent"
current_judge = "default-judge"
agent_models["default-agent"] = old agent
judge_models["default-judge"] = old judge
```

The loader may return the normalized in-memory shape without immediately rewriting the file. Any subsequent save should write the new shape.

## CLI Surface

Existing commands remain:

```powershell
pfae config init
pfae config show
pfae config path
```

New commands:

```powershell
pfae config agent add <name>
pfae config agent use <name>
pfae config agent list
pfae config agent show <name>

pfae config judge add <name>
pfae config judge use <name>
pfae config judge list
pfae config judge show <name>
```

Command behavior:

- `config init`: creates or overwrites both registries with one Agent entry and one Judge entry. It asks for model entry names and model settings.
- `config show`: shows the current Agent and current Judge entry.
- `config agent add <name>`: prompts only for Agent model settings and stores them under `agent_models`.
- `config judge add <name>`: prompts only for Judge model settings and stores them under `judge_models`.
- `config agent use <name>`: sets `current_agent`.
- `config judge use <name>`: sets `current_judge`.
- `config agent list` and `config judge list`: list names and mark the active entry with `*`.
- `config agent show <name>` and `config judge show <name>`: show one entry with masked API key.

## Run Behavior

`pfae run real` resolves config in this order:

```text
CLI arguments > environment variables / .env > user config selected entries > existing defaults
```

The selected Agent entry maps to:

```text
LLM_PROVIDER=openai-compatible
LLM_BASE_URL
LLM_API_KEY
LLM_MODEL
```

The selected Judge entry maps to:

```text
SEMANTIC_JUDGE_PROVIDER=openai-compatible
SEMANTIC_JUDGE_BASE_URL
SEMANTIC_JUDGE_API_KEY
SEMANTIC_JUDGE_MODEL
```

The CLI should update both `os.environ` and in-memory settings before calling runner functions.

## Error Handling

- Unknown Agent entry: fail with a clear message and suggest `pfae config agent list`.
- Unknown Judge entry: fail with a clear message and suggest `pfae config judge list`.
- Missing current Agent or Judge: fail or start `config init` in interactive first-run flow.
- Duplicate add: overwrite the named entry after interactive confirmation is not required for this iteration; print that it was saved.
- Malformed config: fail clearly with the path.

## Safety Rules

- Never print full API keys.
- Never write config inside the repository.
- Never mutate `.env`.
- Do not include user config in git.
- Do not log raw config JSON.
- Secret scan must pass before commit.

## Documentation Updates

Update README and skill docs to describe:

- first setup with `pfae config init`
- adding Agent and Judge models independently
- switching Agent and Judge models independently
- current model display via `pfae config show`

## Testing Strategy

Add focused tests for:

- loading legacy config into the new registry shape
- saving/loading the new registry shape
- listing Agent and Judge models independently
- adding Agent model without changing Judge models
- adding Judge model without changing Agent models
- switching current Agent
- switching current Judge
- showing masked entries
- applying selected entries to environment/settings
- `pfae run real` using selected entries

Manual smoke:

```powershell
pfae config path
pfae config agent list
pfae config judge list
pfae config show
```

Do not enter real API keys in automated tests.

## Acceptance Criteria

- Agent and Judge registries are separate in config and command behavior.
- Initial setup collects one Agent and one Judge model.
- Later model additions can target only Agent or only Judge.
- Switching Agent does not switch Judge.
- Switching Judge does not switch Agent.
- `pfae run real` uses the selected entries.
- Old single-pair config still loads.
- API keys are masked in all display commands.
- Tests and secret scan pass.
