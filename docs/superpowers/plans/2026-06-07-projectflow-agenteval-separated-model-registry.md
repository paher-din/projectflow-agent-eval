# ProjectFlow AgentEval Separated Model Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single Agent/Judge config pair with separate named Agent and Judge model registries that can be added to and switched independently.

**Architecture:** Keep `app.agent_eval.commands.config` as the config boundary. Expand the in-memory config from `AgentEvalUserConfig(agent, judge)` to `AgentEvalUserConfig(current_agent, current_judge, agent_models, judge_models)`, while loading old `agent`/`judge` configs as `default-agent` and `default-judge`. Extend `pfae config` with `agent` and `judge` subcommands and keep `pfae run real` applying only the selected entries.

**Tech Stack:** Python 3.11+, `argparse`, `dataclasses`, `getpass`, `json`, `pytest`.

---

## File Structure

- Modify `app/agent_eval/commands/config.py`: registry config shape, legacy normalization, add/use/list/show helpers.
- Modify `app/agent_eval/cli.py`: nested `config agent` and `config judge` subcommands.
- Modify `tests/test_agent_eval_config.py`: registry behavior, legacy compatibility, independent add/use/list/show.
- Modify `tests/test_agent_eval_cli.py`: CLI dispatch tests for new nested commands.
- Modify `README.md`: document independent Agent/Judge model management.
- Modify `skills/projectflow-agent-eval/SKILL.md`: instruct agents not to mix Agent and Judge model commands.
- Modify `skills/projectflow-agent-eval/references/command-guide.md`: add model registry commands.

## Task 1: Registry Config Shape and Legacy Load

**Files:**
- Modify: `app/agent_eval/commands/config.py`
- Modify: `tests/test_agent_eval_config.py`

- [ ] **Step 1: Write failing tests for new shape and legacy migration**

Add or update tests in `tests/test_agent_eval_config.py`:

```python
def test_save_and_load_registry_config(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    agent_key = "agent-key"
    judge_key = "judge-key"
    config = AgentEvalUserConfig(
        current_agent="agent-main",
        current_judge="judge-main",
        agent_models={
            "agent-main": ModelConfig(base_url="https://agent.example/v1", api_key=agent_key, model="agent-model")
        },
        judge_models={
            "judge-main": ModelConfig(base_url="https://judge.example/v1", api_key=judge_key, model="judge-model")
        },
    )

    save_user_config(config, path)

    loaded = load_user_config(path)
    assert loaded == config


def test_load_legacy_pair_config_normalizes_to_default_names(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "agent": {
                    "base_url": "https://agent.example/v1",
                    "api_key": "legacy-agent-key",
                    "model": "agent-model",
                },
                "judge": {
                    "base_url": "https://judge.example/v1",
                    "api_key": "legacy-judge-key",
                    "model": "judge-model",
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = load_user_config(path)

    assert loaded is not None
    assert loaded.current_agent == "default-agent"
    assert loaded.current_judge == "default-judge"
    assert loaded.agent_models["default-agent"].model == "agent-model"
    assert loaded.judge_models["default-judge"].model == "judge-model"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_agent_eval_config.py -v
```

Expected: FAIL because `AgentEvalUserConfig` still expects `agent` and `judge`.

- [ ] **Step 3: Implement registry shape**

Update `app/agent_eval/commands/config.py`:

```python
@dataclass(frozen=True)
class AgentEvalUserConfig:
    current_agent: str
    current_judge: str
    agent_models: dict[str, ModelConfig]
    judge_models: dict[str, ModelConfig]

    @property
    def agent(self) -> ModelConfig:
        try:
            return self.agent_models[self.current_agent]
        except KeyError as exc:
            raise CommandError(f"Current Agent model not found: {self.current_agent}") from exc

    @property
    def judge(self) -> ModelConfig:
        try:
            return self.judge_models[self.current_judge]
        except KeyError as exc:
            raise CommandError(f"Current Judge model not found: {self.current_judge}") from exc
```

Add helper:

```python
def _model_config_map(raw: dict[str, object]) -> dict[str, ModelConfig]:
    return {name: ModelConfig(**value) for name, value in raw.items()}
```

Update `load_user_config` to accept both shapes:

```python
raw = json.loads(...)
if "agent" in raw and "judge" in raw:
    return AgentEvalUserConfig(
        current_agent="default-agent",
        current_judge="default-judge",
        agent_models={"default-agent": ModelConfig(**raw["agent"])},
        judge_models={"default-judge": ModelConfig(**raw["judge"])},
    )
return AgentEvalUserConfig(
    current_agent=raw["current_agent"],
    current_judge=raw["current_judge"],
    agent_models=_model_config_map(raw["agent_models"]),
    judge_models=_model_config_map(raw["judge_models"]),
)
```

`save_user_config` can still use `asdict(config)`.

- [ ] **Step 4: Update existing tests to use registry shape**

Where tests construct `AgentEvalUserConfig(agent=..., judge=...)`, replace with:

```python
AgentEvalUserConfig(
    current_agent="agent-main",
    current_judge="judge-main",
    agent_models={"agent-main": agent_model},
    judge_models={"judge-main": judge_model},
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_agent_eval_config.py -v
```

Expected: PASS.

## Task 2: Independent Add/Use/List/Show Helpers

**Files:**
- Modify: `app/agent_eval/commands/config.py`
- Modify: `tests/test_agent_eval_config.py`

- [ ] **Step 1: Write failing tests for independent registries**

Add tests:

```python
def test_add_agent_model_does_not_change_judge_models(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    save_user_config(_registry_config(), path)

    config_agent_add("agent-alt", path=path, input_func=_input_values("https://agent2.example/v1", "agent2-model"), getpass_func=_secret_values("agent2-key"))

    loaded = load_user_config(path)
    assert loaded is not None
    assert "agent-alt" in loaded.agent_models
    assert list(loaded.judge_models) == ["judge-main"]


def test_add_judge_model_does_not_change_agent_models(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    save_user_config(_registry_config(), path)

    config_judge_add("judge-alt", path=path, input_func=_input_values("https://judge2.example/v1", "judge2-model"), getpass_func=_secret_values("judge2-key"))

    loaded = load_user_config(path)
    assert loaded is not None
    assert "judge-alt" in loaded.judge_models
    assert list(loaded.agent_models) == ["agent-main"]


def test_use_agent_does_not_switch_judge(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = _registry_config()
    config = AgentEvalUserConfig(
        current_agent=config.current_agent,
        current_judge=config.current_judge,
        agent_models={**config.agent_models, "agent-alt": ModelConfig("https://agent2.example/v1", "agent2-key", "agent2-model")},
        judge_models=config.judge_models,
    )
    save_user_config(config, path)

    config_agent_use("agent-alt", path=path)

    loaded = load_user_config(path)
    assert loaded.current_agent == "agent-alt"
    assert loaded.current_judge == "judge-main"


def test_use_judge_does_not_switch_agent(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = _registry_config()
    config = AgentEvalUserConfig(
        current_agent=config.current_agent,
        current_judge=config.current_judge,
        agent_models=config.agent_models,
        judge_models={**config.judge_models, "judge-alt": ModelConfig("https://judge2.example/v1", "judge2-key", "judge2-model")},
    )
    save_user_config(config, path)

    config_judge_use("judge-alt", path=path)

    loaded = load_user_config(path)
    assert loaded.current_agent == "agent-main"
    assert loaded.current_judge == "judge-alt"
```

Add helper functions in tests:

```python
def _registry_config() -> AgentEvalUserConfig:
    return AgentEvalUserConfig(
        current_agent="agent-main",
        current_judge="judge-main",
        agent_models={"agent-main": ModelConfig("https://agent.example/v1", "agent-key", "agent-model")},
        judge_models={"judge-main": ModelConfig("https://judge.example/v1", "judge-key", "judge-model")},
    )


def _input_values(*values: str):
    items = iter(values)
    return lambda prompt: next(items)


def _secret_values(*values: str):
    items = iter(values)
    return lambda prompt: next(items)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_agent_eval_config.py -v
```

Expected: FAIL because add/use functions do not exist.

- [ ] **Step 3: Implement helper commands**

Add to `config.py`:

```python
def _load_or_empty_config(path: Path | None = None) -> AgentEvalUserConfig | None:
    return load_user_config(path)


def _prompt_model_config(role: str, *, input_func=input, getpass_func=getpass) -> ModelConfig:
    return ModelConfig(
        base_url=_prompt_required(f"{role} base URL", input_func=input_func),
        api_key=_prompt_secret(f"{role} API key", getpass_func=getpass_func),
        model=_prompt_required(f"{role} model", input_func=input_func),
    )


def config_agent_add(name: str, *, path: Path | None = None, input_func=input, getpass_func=getpass) -> int:
    config = load_user_config(path)
    model = _prompt_model_config("Agent LLM", input_func=input_func, getpass_func=getpass_func)
    if config is None:
        config = AgentEvalUserConfig(name, "", {name: model}, {})
    else:
        config = AgentEvalUserConfig(config.current_agent or name, config.current_judge, {**config.agent_models, name: model}, config.judge_models)
    save_user_config(config, path)
    print(f"Saved Agent model: {name}")
    return 0
```

Implement analogous `config_judge_add`, `config_agent_use`, `config_judge_use`, `config_agent_list`, `config_judge_list`, `config_agent_show`, `config_judge_show`.

Use `CommandError` for unknown names and include the right list command suggestion.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_agent_eval_config.py -v
```

Expected: PASS.

## Task 3: CLI Routes and Init Flow

**Files:**
- Modify: `app/agent_eval/cli.py`
- Modify: `app/agent_eval/commands/config.py`
- Modify: `tests/test_agent_eval_cli.py`
- Modify: `tests/test_agent_eval_config.py`

- [ ] **Step 1: Write failing CLI dispatch tests**

Add tests:

```python
def test_cli_config_agent_use_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agent_eval.commands.config as config_commands
    monkeypatch.setattr(config_commands, "config_agent_use", lambda name, **kwargs: 0)
    assert main(["config", "agent", "use", "agent-main"]) == 0


def test_cli_config_judge_use_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agent_eval.commands.config as config_commands
    monkeypatch.setattr(config_commands, "config_judge_use", lambda name, **kwargs: 0)
    assert main(["config", "judge", "use", "judge-main"]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_agent_eval_cli.py::test_cli_config_agent_use_dispatches tests/test_agent_eval_cli.py::test_cli_config_judge_use_dispatches -v
```

Expected: FAIL because routes do not exist.

- [ ] **Step 3: Add nested argparse routes**

In `cli.py`, under config parser:

```python
    config_agent = config_sub.add_parser("agent", help="Manage Agent model entries")
    config_agent_sub = config_agent.add_subparsers(dest="config_agent_command")
    agent_add = config_agent_sub.add_parser("add", help="Add Agent model")
    agent_add.add_argument("name")
    agent_use = config_agent_sub.add_parser("use", help="Use Agent model")
    agent_use.add_argument("name")
    config_agent_sub.add_parser("list", help="List Agent models")
    agent_show = config_agent_sub.add_parser("show", help="Show Agent model")
    agent_show.add_argument("name")
```

Repeat for `judge`.

In dispatch, route to corresponding config functions.

- [ ] **Step 4: Update `config_init` for named entries**

`config_init` should prompt for:

```text
Agent model name
Agent LLM base URL
Agent LLM API key
Agent LLM model
Judge model name
Judge LLM base URL
Judge LLM API key
Judge LLM model
```

It should save:

```python
AgentEvalUserConfig(
    current_agent=agent_name,
    current_judge=judge_name,
    agent_models={agent_name: agent_model},
    judge_models={judge_name: judge_model},
)
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m pytest tests/test_agent_eval_config.py tests/test_agent_eval_cli.py -v
```

Expected: PASS.

## Task 4: Apply Selected Entries and Update Docs

**Files:**
- Modify: `app/agent_eval/commands/config.py`
- Modify: `README.md`
- Modify: `skills/projectflow-agent-eval/SKILL.md`
- Modify: `skills/projectflow-agent-eval/references/command-guide.md`
- Modify: `tests/test_agent_eval_config.py`

- [ ] **Step 1: Ensure selected entries drive env/settings**

Add test:

```python
def test_apply_user_config_uses_selected_agent_and_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AgentEvalUserConfig(
        current_agent="agent-alt",
        current_judge="judge-alt",
        agent_models={
            "agent-main": ModelConfig("https://agent1.example/v1", "agent1-key", "agent1-model"),
            "agent-alt": ModelConfig("https://agent2.example/v1", "agent2-key", "agent2-model"),
        },
        judge_models={
            "judge-main": ModelConfig("https://judge1.example/v1", "judge1-key", "judge1-model"),
            "judge-alt": ModelConfig("https://judge2.example/v1", "judge2-key", "judge2-model"),
        },
    )

    apply_user_config_to_env(config)

    import os
    assert os.environ["LLM_MODEL"] == "agent2-model"
    assert os.environ["SEMANTIC_JUDGE_MODEL"] == "judge2-model"
```

- [ ] **Step 2: Run test to verify behavior**

Run:

```powershell
python -m pytest tests/test_agent_eval_config.py::test_apply_user_config_uses_selected_agent_and_judge -v
```

Expected: PASS after earlier registry changes.

- [ ] **Step 3: Update README**

Add:

```markdown
### Add Or Switch Models

Agent and judge models are managed separately:

```powershell
pfae config agent add deepseek-pro
pfae config agent use deepseek-pro
pfae config agent list

pfae config judge add deepseek-flash
pfae config judge use deepseek-flash
pfae config judge list
```

`pfae run real` uses the current Agent model and current Judge model.
```

- [ ] **Step 4: Update skill and command guide**

Add commands and explicit instruction: do not use `config judge ...` to manage Agent models or `config agent ...` to manage Judge models.

- [ ] **Step 5: Run docs scan**

Run:

```powershell
Select-String -Path 'README.md','skills/projectflow-agent-eval/SKILL.md','skills/projectflow-agent-eval/references/command-guide.md' -Pattern 'T[B]D|T[O]DO|PLACE[H]OLDER' -CaseSensitive:$false
```

Expected: no matches.

## Task 5: Verification and Commit

**Files:**
- Modify only if verification exposes a bug.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
python -m pytest tests/test_agent_eval_config.py tests/test_agent_eval_cli.py -v
```

Expected: PASS.

- [ ] **Step 2: Run full tests**

Run:

```powershell
python -m pytest -v
```

Expected: PASS.

- [ ] **Step 3: Run new-code lint**

Run:

```powershell
python -m ruff check app/agent_eval/cli.py app/agent_eval/commands tests/test_agent_eval_cli.py tests/test_agent_eval_config.py
```

Expected: PASS.

- [ ] **Step 4: Smoke commands**

Run:

```powershell
pfae config --help
pfae config agent --help
pfae config judge --help
pfae config path
```

Expected: all return successfully and do not print secrets.

- [ ] **Step 5: Secret scan**

Run:

```powershell
$files = @(git ls-files) + @(git ls-files --others --exclude-standard) | Sort-Object -Unique
$patterns = @(
  'sk-[A-Za-z0-9_-]{20,}',
  'AKIA[0-9A-Z]{16}',
  '-----BEGIN (RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----',
  '(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*["''][^"'']{8,}["'']'
)
$hits = @()
foreach ($file in $files) {
  if (Test-Path -LiteralPath $file) {
    foreach ($pattern in $patterns) {
      $match = Select-String -LiteralPath $file -Pattern $pattern -ErrorAction SilentlyContinue
      if ($match) { $hits += $match }
    }
  }
}
if ($hits.Count -gt 0) {
  $hits | ForEach-Object { "${($_.Path)}:$($_.LineNumber): $($_.Line.Trim())" }
  exit 1
}
"Secret scan passed."
```

Expected: `Secret scan passed.`

- [ ] **Step 6: Commit**

Do not stage `AGENTS.md` if it remains a pre-existing user change.

```powershell
git add app/agent_eval/commands/config.py app/agent_eval/cli.py tests/test_agent_eval_config.py tests/test_agent_eval_cli.py README.md skills/projectflow-agent-eval/SKILL.md skills/projectflow-agent-eval/references/command-guide.md
git commit -m "feat: separate AgentEval agent and judge model registries"
```

## Self-Review

- Spec coverage: The plan covers separate registries, legacy config loading, independent add/use/list/show, run real selected entry application, docs, tests, lint, smoke, and secret scan.
- Marker scan: No unfinished-work markers are intentionally left in this plan.
- Type consistency: The plan consistently uses `AgentEvalUserConfig`, `ModelConfig`, `agent_models`, `judge_models`, `current_agent`, `current_judge`, `config_agent_*`, and `config_judge_*`.
