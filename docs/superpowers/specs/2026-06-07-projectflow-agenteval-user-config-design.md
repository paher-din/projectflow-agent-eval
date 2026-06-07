# ProjectFlow AgentEval User Config Design

**Date:** 2026-06-07  
**Status:** Approved design  
**Scope:** Add first-run real LLM configuration for the `pfae` CLI.

## Decision

ProjectFlow AgentEval will support a user-level real-mode configuration wizard. When a user downloads the CLI and runs real-mode evaluation without existing provider settings, `pfae` should ask for the agent model and auxiliary judge model settings, save them outside the repository, and reuse that configuration for later real-mode runs.

The CLI must not write secrets into `.env`, reports, logs, commits, or benchmark output metadata.

## Goals

- Make first real-mode use straightforward for users who do not know the existing `.env` contract.
- Configure two model roles:
  - Agent LLM: the model being evaluated.
  - Judge LLM: the auxiliary semantic judge model.
- Store user-provided `base_url`, `api_key`, and `model` for both roles.
- Reuse the stored configuration automatically after setup.
- Keep `.env` and environment variable compatibility.
- Avoid adding a dependency for key storage in the first version.

## Non-Goals

- Do not build a provider marketplace.
- Do not validate every provider-specific model name.
- Do not encrypt keys in the first version.
- Do not modify `.env`.
- Do not change benchmark report schemas to include secrets.

## Configuration Location

Use a user-level JSON file:

```text
Windows: %APPDATA%\ProjectFlow-AgentEval\config.json
macOS/Linux: ~/.config/projectflow-agent-eval/config.json
```

The file stores secrets in plaintext. This is acceptable for the first version because it is outside the repository and avoids extra dependencies, but commands must make the trade-off explicit during setup.

Example:

```json
{
  "agent": {
    "base_url": "https://api.deepseek.com",
    "api_key": "user-agent-key",
    "model": "deepseek-v4-pro"
  },
  "judge": {
    "base_url": "https://api.deepseek.com",
    "api_key": "user-judge-key",
    "model": "deepseek-v4-flash"
  }
}
```

## CLI Surface

Add:

```powershell
pfae config init
pfae config show
pfae config path
```

Behavior:

- `pfae config init`: interactive setup or overwrite. Prompt for agent and judge `base_url`, `api_key`, and `model`. API key input must be hidden.
- `pfae config show`: print configured base URLs and models, but mask API keys.
- `pfae config path`: print the resolved config path.
- `pfae run real`: if no env or user config exists, enter `config init` before running. If the user cancels setup, exit with a clear non-zero error.

## Configuration Precedence

Use this precedence for real-mode values:

```text
CLI arguments > environment variables / .env > user config > existing defaults
```

Specific mapping:

- Agent:
  - `LLM_BASE_URL`
  - `LLM_API_KEY`
  - `LLM_MODEL`
- Judge:
  - `SEMANTIC_JUDGE_BASE_URL`
  - `SEMANTIC_JUDGE_API_KEY`
  - `SEMANTIC_JUDGE_MODEL`

The CLI should apply user config to process environment variables before invoking existing runner code, so the current settings system can remain mostly unchanged.

## Safety Rules

- Never print full API keys.
- Never write user config under the repository root.
- Never commit user config.
- Do not mutate `.env`.
- `pfae config show` masks keys as `prefix...suffix`, or `<not set>`.
- Error messages must mention missing config without leaking provided values.
- Reports may include provider host and model names, but not full keys.

## Error Handling

- If the config file is malformed, `pfae config show` should fail clearly with the path.
- If `pfae run real` finds partial config, it should prompt to complete setup instead of failing deep inside the LLM client.
- If input is canceled during setup, exit with `Configuration was canceled`.
- Empty required values should re-prompt in interactive mode.
- In non-interactive mode, commands should fail clearly rather than waiting for hidden input.

## Skill Updates

Update `skills/projectflow-agent-eval/SKILL.md` and command reference:

- When real mode lacks provider configuration, use `pfae config init`.
- Do not ask the user to put keys in `.env`.
- Do not display full keys in summaries.
- Prefer `pfae config show` for checking configured model names.

## Testing Strategy

Add focused tests for:

- Config path resolution with fake environment variables.
- Loading missing, valid, and malformed config.
- Masking API keys.
- Applying user config to environment values without overriding explicit CLI args.
- `pfae config show` output.
- `pfae run real` triggering setup when no config exists.
- `pfae run real` not triggering setup when environment variables already exist.

Manual verification:

```powershell
pfae config path
pfae config init
pfae config show
pfae run real --model deepseek-v4-pro
```

Do not run a real benchmark with user-provided keys in automated tests.

## Acceptance Criteria

- A fresh user can run `pfae run real` and be guided through setup.
- Stored config is outside the repository.
- Later real-mode runs reuse the saved config.
- `pfae config show` masks keys.
- Existing `.env` / environment variable usage still works.
- `pfae run mock` remains credential-free.
- No API keys appear in tests, reports, logs, git diffs, or commits.
