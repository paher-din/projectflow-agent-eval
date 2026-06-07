# ProjectFlow AgentEval User Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-run user-level configuration wizard so `pfae run real` can collect and reuse Agent LLM and judge LLM settings without writing secrets into the repository.

**Architecture:** Add a focused config module under `app.agent_eval.commands` for path resolution, JSON load/save, key masking, and process environment application. Extend `app.agent_eval.cli` with `pfae config init|show|path`, and update `runs.py` so real-mode runs bootstrap missing config before calling the existing runner. Keep `.env` compatibility and keep the benchmark runner as the execution core.

**Tech Stack:** Python 3.11+, `argparse`, `dataclasses`, `getpass`, `json`, existing `pytest` tests.

---

## File Structure

- Create `app/agent_eval/commands/config.py`: user config model, path resolution, load/save, masking, setup prompt, environment application.
- Modify `app/agent_eval/cli.py`: add `config` subcommands and dispatch.
- Modify `app/agent_eval/commands/runs.py`: apply config for real mode, optionally run first-use setup.
- Modify `tests/test_agent_eval_cli.py`: keep existing CLI tests green and add command dispatch coverage.
- Create `tests/test_agent_eval_config.py`: focused config tests.
- Modify `README.md`: add first-run config usage.
- Modify `skills/projectflow-agent-eval/SKILL.md`: tell agents to use `pfae config init` for missing real-mode config.
- Modify `skills/projectflow-agent-eval/references/command-guide.md`: add config commands.

## Task 1: User Config Model and Helpers

**Files:**
- Create: `app/agent_eval/commands/config.py`
- Test: `tests/test_agent_eval_config.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_agent_eval_config.py`:

```python
import json
from pathlib import Path

import pytest

from app.agent_eval.commands.common import CommandError
from app.agent_eval.commands.config import (
    AgentEvalUserConfig,
    ModelConfig,
    apply_user_config_to_env,
    config_path,
    load_user_config,
    mask_secret,
    save_user_config,
)


def test_config_path_uses_appdata_on_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))

    path = config_path(platform_name="nt")

    assert path == tmp_path / "Roaming" / "ProjectFlow-AgentEval" / "config.json"


def test_config_path_uses_xdg_config_home_on_posix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    path = config_path(platform_name="posix")

    assert path == tmp_path / "xdg" / "projectflow-agent-eval" / "config.json"


def test_save_and_load_user_config(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    agent_key = "agent-key"
    judge_key = "judge-key"
    config = AgentEvalUserConfig(
        agent=ModelConfig(base_url="https://agent.example/v1", api_key=agent_key, model="agent-model"),
        judge=ModelConfig(base_url="https://judge.example/v1", api_key=judge_key, model="judge-model"),
    )

    save_user_config(config, path)

    assert load_user_config(path) == config


def test_load_missing_user_config_returns_none(tmp_path: Path) -> None:
    assert load_user_config(tmp_path / "missing.json") is None


def test_load_malformed_user_config_raises_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(CommandError, match="Malformed user config"):
        load_user_config(path)


def test_mask_secret_hides_middle() -> None:
    assert mask_secret("abcdef123456") == "abcd...3456"
    assert mask_secret("") == "<not set>"
    assert mask_secret(None) == "<not set>"


def test_apply_user_config_to_env_does_not_override_existing_values(monkeypatch: pytest.MonkeyPatch) -> None:
    agent_key = "agent-key"
    judge_key = "judge-key"
    config = AgentEvalUserConfig(
        agent=ModelConfig(base_url="https://agent.example/v1", api_key=agent_key, model="agent-model"),
        judge=ModelConfig(base_url="https://judge.example/v1", api_key=judge_key, model="judge-model"),
    )
    monkeypatch.setenv("LLM_MODEL", "env-agent-model")

    apply_user_config_to_env(config)

    assert __import__("os").environ["LLM_MODEL"] == "env-agent-model"
    assert __import__("os").environ["LLM_BASE_URL"] == "https://agent.example/v1"
    assert __import__("os").environ["LLM_API_KEY"] == "agent-key"
    assert __import__("os").environ["SEMANTIC_JUDGE_BASE_URL"] == "https://judge.example/v1"
    assert __import__("os").environ["SEMANTIC_JUDGE_API_KEY"] == "judge-key"
    assert __import__("os").environ["SEMANTIC_JUDGE_MODEL"] == "judge-model"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_agent_eval_config.py -v
```

Expected: FAIL with `ModuleNotFoundError` or missing symbols from `app.agent_eval.commands.config`.

- [ ] **Step 3: Implement config helpers**

Create `app/agent_eval/commands/config.py`:

```python
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from getpass import getpass
from pathlib import Path
from typing import Callable

from app.agent_eval.commands.common import CommandError


@dataclass(frozen=True)
class ModelConfig:
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class AgentEvalUserConfig:
    agent: ModelConfig
    judge: ModelConfig


def config_path(*, platform_name: str | None = None) -> Path:
    selected_platform = platform_name or os.name
    if selected_platform == "nt":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return root / "ProjectFlow-AgentEval" / "config.json"
    root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "projectflow-agent-eval" / "config.json"


def load_user_config(path: Path | None = None) -> AgentEvalUserConfig | None:
    selected_path = path or config_path()
    if not selected_path.exists():
        return None
    try:
        raw = json.loads(selected_path.read_text(encoding="utf-8"))
        return AgentEvalUserConfig(
            agent=ModelConfig(**raw["agent"]),
            judge=ModelConfig(**raw["judge"]),
        )
    except json.JSONDecodeError as exc:
        raise CommandError(f"Malformed user config: {selected_path}: {exc}") from exc
    except (KeyError, TypeError) as exc:
        raise CommandError(f"Invalid user config shape: {selected_path}: {exc}") from exc


def save_user_config(config: AgentEvalUserConfig, path: Path | None = None) -> Path:
    selected_path = path or config_path()
    selected_path.parent.mkdir(parents=True, exist_ok=True)
    selected_path.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
    return selected_path


def mask_secret(value: str | None) -> str:
    if not value:
        return "<not set>"
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def apply_user_config_to_env(config: AgentEvalUserConfig) -> None:
    defaults = {
        "LLM_PROVIDER": "openai-compatible",
        "LLM_BASE_URL": config.agent.base_url,
        "LLM_API_KEY": config.agent.api_key,
        "LLM_MODEL": config.agent.model,
        "SEMANTIC_JUDGE_PROVIDER": "openai-compatible",
        "SEMANTIC_JUDGE_BASE_URL": config.judge.base_url,
        "SEMANTIC_JUDGE_API_KEY": config.judge.api_key,
        "SEMANTIC_JUDGE_MODEL": config.judge.model,
    }
    for key, value in defaults.items():
        if not os.environ.get(key):
            os.environ[key] = value


def _prompt_required(label: str, *, input_func: Callable[[str], str] = input) -> str:
    while True:
        value = input_func(f"{label}: ").strip()
        if value:
            return value
        print(f"{label} is required.")


def _prompt_secret(label: str, *, getpass_func: Callable[[str], str] = getpass) -> str:
    while True:
        value = getpass_func(f"{label}: ").strip()
        if value:
            return value
        print(f"{label} is required.")


def prompt_user_config(
    *,
    input_func: Callable[[str], str] = input,
    getpass_func: Callable[[str], str] = getpass,
) -> AgentEvalUserConfig:
    print("Configure ProjectFlow AgentEval real-mode models.")
    print("API keys are stored in a user-level config file, not in this repository.")
    agent = ModelConfig(
        base_url=_prompt_required("Agent LLM base URL", input_func=input_func),
        api_key=_prompt_secret("Agent LLM API key", getpass_func=getpass_func),
        model=_prompt_required("Agent LLM model", input_func=input_func),
    )
    judge = ModelConfig(
        base_url=_prompt_required("Judge LLM base URL", input_func=input_func),
        api_key=_prompt_secret("Judge LLM API key", getpass_func=getpass_func),
        model=_prompt_required("Judge LLM model", input_func=input_func),
    )
    return AgentEvalUserConfig(agent=agent, judge=judge)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m pytest tests/test_agent_eval_config.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run secret scan first, then:

```powershell
git add app/agent_eval/commands/config.py tests/test_agent_eval_config.py
git commit -m "feat: add AgentEval user config helpers"
```

## Task 2: Config CLI Commands

**Files:**
- Modify: `app/agent_eval/commands/config.py`
- Modify: `app/agent_eval/cli.py`
- Modify: `tests/test_agent_eval_cli.py`
- Modify: `tests/test_agent_eval_config.py`

- [ ] **Step 1: Write failing tests for config commands**

Append to `tests/test_agent_eval_config.py`:

```python
from app.agent_eval.commands.config import config_init, config_path_command, config_show


def test_config_path_command_prints_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = config_path_command(path=tmp_path / "config.json")

    captured = capsys.readouterr()
    assert exit_code == 0
    assert str(tmp_path / "config.json") in captured.out


def test_config_show_masks_keys(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "config.json"
    agent_key = "agent-secret-key"
    judge_key = "judge-secret-key"
    save_user_config(
        AgentEvalUserConfig(
            agent=ModelConfig(base_url="https://agent.example/v1", api_key=agent_key, model="agent-model"),
            judge=ModelConfig(base_url="https://judge.example/v1", api_key=judge_key, model="judge-model"),
        ),
        path,
    )

    exit_code = config_show(path=path)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "agent-model" in captured.out
    assert "agent-secret-key" not in captured.out
    assert "agen...-key" in captured.out


def test_config_init_saves_prompted_values(tmp_path: Path) -> None:
    inputs = iter([
        "https://agent.example/v1",
        "agent-model",
        "https://judge.example/v1",
        "judge-model",
    ])
    secrets = iter(["agent-key", "judge-key"])

    exit_code = config_init(
        path=tmp_path / "config.json",
        input_func=lambda prompt: next(inputs),
        getpass_func=lambda prompt: next(secrets),
    )

    assert exit_code == 0
    config = load_user_config(tmp_path / "config.json")
    assert config is not None
    assert config.agent.api_key == "agent-key"
    assert config.judge.model == "judge-model"
```

Append to `tests/test_agent_eval_cli.py`:

```python
import app.agent_eval.commands.config as config_commands


def test_cli_config_path_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_commands, "config_path_command", lambda: 0)

    assert main(["config", "path"]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_agent_eval_config.py tests/test_agent_eval_cli.py::test_cli_config_path_dispatches -v
```

Expected: FAIL because command functions or parser route are missing.

- [ ] **Step 3: Implement command functions and parser route**

Add to `app/agent_eval/commands/config.py`:

```python
def config_path_command(*, path: Path | None = None) -> int:
    print(path or config_path())
    return 0


def config_show(*, path: Path | None = None) -> int:
    selected_path = path or config_path()
    config = load_user_config(selected_path)
    if config is None:
        raise CommandError(f"No user config found at {selected_path}. Run `pfae config init`.")
    print(f"Config path: {selected_path}")
    print("Agent LLM:")
    print(f"  base_url: {config.agent.base_url}")
    print(f"  model: {config.agent.model}")
    print(f"  api_key: {mask_secret(config.agent.api_key)}")
    print("Judge LLM:")
    print(f"  base_url: {config.judge.base_url}")
    print(f"  model: {config.judge.model}")
    print(f"  api_key: {mask_secret(config.judge.api_key)}")
    return 0


def config_init(
    *,
    path: Path | None = None,
    input_func: Callable[[str], str] = input,
    getpass_func: Callable[[str], str] = getpass,
) -> int:
    try:
        config = prompt_user_config(input_func=input_func, getpass_func=getpass_func)
    except (EOFError, KeyboardInterrupt) as exc:
        raise CommandError("Configuration was canceled.") from exc
    saved_path = save_user_config(config, path)
    print(f"Saved user config: {saved_path}")
    print("API keys were stored in the user-level config file and will not be printed.")
    return 0
```

Modify `app/agent_eval/cli.py`:

```python
from app.agent_eval.commands.config import config_init, config_path_command, config_show
```

Add parser before `return parser`:

```python
    config_parser = sub.add_parser("config", help="Manage real-mode LLM config")
    config_sub = config_parser.add_subparsers(dest="config_command")
    config_sub.add_parser("init", help="Create or overwrite user config")
    config_sub.add_parser("show", help="Show masked user config")
    config_sub.add_parser("path", help="Show user config path")
```

Add dispatch:

```python
    if args.command == "config" and args.config_command == "init":
        return config_init()
    if args.command == "config" and args.config_command == "show":
        return config_show()
    if args.command == "config" and args.config_command == "path":
        return config_path_command()
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_agent_eval_config.py tests/test_agent_eval_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run secret scan first, then:

```powershell
git add app/agent_eval/commands/config.py app/agent_eval/cli.py tests/test_agent_eval_cli.py tests/test_agent_eval_config.py
git commit -m "feat: add AgentEval config commands"
```

## Task 3: Real-Mode First-Run Bootstrap

**Files:**
- Modify: `app/agent_eval/commands/config.py`
- Modify: `app/agent_eval/commands/runs.py`
- Test: `tests/test_agent_eval_config.py`
- Test: `tests/test_agent_eval_cli.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_agent_eval_config.py`:

```python
from app.agent_eval.commands.config import has_real_llm_env, ensure_real_config


def test_has_real_llm_env_requires_agent_and_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
        "SEMANTIC_JUDGE_BASE_URL",
        "SEMANTIC_JUDGE_API_KEY",
        "SEMANTIC_JUDGE_MODEL",
    ]:
        monkeypatch.delenv(key, raising=False)

    assert has_real_llm_env() is False
    monkeypatch.setenv("LLM_BASE_URL", "https://agent.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "agent-key")
    monkeypatch.setenv("LLM_MODEL", "agent-model")
    monkeypatch.setenv("SEMANTIC_JUDGE_BASE_URL", "https://judge.example/v1")
    monkeypatch.setenv("SEMANTIC_JUDGE_API_KEY", "judge-key")
    monkeypatch.setenv("SEMANTIC_JUDGE_MODEL", "judge-model")

    assert has_real_llm_env() is True


def test_ensure_real_config_applies_saved_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in [
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
        "SEMANTIC_JUDGE_BASE_URL",
        "SEMANTIC_JUDGE_API_KEY",
        "SEMANTIC_JUDGE_MODEL",
    ]:
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "config.json"
    agent_key = "agent-key"
    judge_key = "judge-key"
    save_user_config(
        AgentEvalUserConfig(
            agent=ModelConfig(base_url="https://agent.example/v1", api_key=agent_key, model="agent-model"),
            judge=ModelConfig(base_url="https://judge.example/v1", api_key=judge_key, model="judge-model"),
        ),
        path,
    )

    ensure_real_config(path=path, interactive=False)

    assert __import__("os").environ["LLM_MODEL"] == "agent-model"
    assert __import__("os").environ["SEMANTIC_JUDGE_MODEL"] == "judge-model"


def test_ensure_real_config_fails_noninteractive_without_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    with pytest.raises(CommandError, match="No real LLM config found"):
        ensure_real_config(path=tmp_path / "missing.json", interactive=False)
```

Append to `tests/test_agent_eval_cli.py`:

```python
def test_run_real_ensures_config_before_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(run_commands, "ensure_real_config", lambda: calls.append("config"))

    def fake_run_suite(fixtures: str, **kwargs: object) -> tuple[list[object], object]:
        calls.append("run")

        class Summary:
            run_id = "run-1"
            model = "model"
            cases_passed = 1
            cases_total = 1
            average_score = 1.0
            hard_failure_count = 0
            duration_seconds = 0.1
            cases_failed = 0
            cases_judge_failed = 0

        return [], Summary()

    monkeypatch.setattr(run_commands, "run_suite", fake_run_suite)

    assert run_commands.run_benchmark("real") == 0
    assert calls == ["config", "run"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_agent_eval_config.py tests/test_agent_eval_cli.py::test_run_real_ensures_config_before_runner -v
```

Expected: FAIL because `ensure_real_config` is missing or not called.

- [ ] **Step 3: Implement first-run bootstrap**

Add to `app/agent_eval/commands/config.py`:

```python
def has_real_llm_env() -> bool:
    required = [
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
        "SEMANTIC_JUDGE_BASE_URL",
        "SEMANTIC_JUDGE_API_KEY",
        "SEMANTIC_JUDGE_MODEL",
    ]
    return all(bool(os.environ.get(key)) for key in required)


def ensure_real_config(*, path: Path | None = None, interactive: bool = True) -> None:
    if has_real_llm_env():
        return
    selected_path = path or config_path()
    config = load_user_config(selected_path)
    if config is not None:
        apply_user_config_to_env(config)
        return
    if not interactive:
        raise CommandError(f"No real LLM config found. Run `pfae config init` to create {selected_path}.")
    print("No real LLM config found. Starting first-run setup.")
    config_init(path=selected_path)
    config = load_user_config(selected_path)
    if config is None:
        raise CommandError("Configuration was canceled.")
    apply_user_config_to_env(config)
```

Modify `app/agent_eval/commands/runs.py`:

```python
from app.agent_eval.commands.config import ensure_real_config
```

Inside `run_benchmark`, before `run_suite(...)`:

```python
    if mode == "real":
        ensure_real_config()
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_agent_eval_config.py tests/test_agent_eval_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run secret scan first, then:

```powershell
git add app/agent_eval/commands/config.py app/agent_eval/commands/runs.py tests/test_agent_eval_cli.py tests/test_agent_eval_config.py
git commit -m "feat: bootstrap real-mode LLM config"
```

## Task 4: Documentation and Skill Updates

**Files:**
- Modify: `README.md`
- Modify: `skills/projectflow-agent-eval/SKILL.md`
- Modify: `skills/projectflow-agent-eval/references/command-guide.md`

- [ ] **Step 1: Update README**

In `README.md`, add this under `## CLI Toolkit`:

```markdown
### First Real-Mode Setup

For real LLM runs, configure the evaluated Agent model and auxiliary judge model once:

```powershell
pfae config init
pfae config show
```

The config is stored outside this repository in your user config directory. API keys are masked in `config show` output and must not be committed.

After setup:

```powershell
pfae run real
```
```

- [ ] **Step 2: Update skill**

In `skills/projectflow-agent-eval/SKILL.md`, add:

```markdown
## Real-Mode Setup

When real mode lacks provider configuration, run `pfae config init`. Do not ask the user to put keys in `.env` unless they explicitly prefer that. Use `pfae config show` to confirm configured model names; never display full API keys.
```

- [ ] **Step 3: Update command guide**

In `skills/projectflow-agent-eval/references/command-guide.md`, add:

```markdown
## Configure Real Models

```powershell
pfae config path
pfae config init
pfae config show
```

`pfae run real` starts setup automatically when no environment or user config exists.
```

- [ ] **Step 4: Run documentation scan**

Run:

```powershell
Select-String -Path 'README.md','skills/projectflow-agent-eval/SKILL.md','skills/projectflow-agent-eval/references/command-guide.md' -Pattern 'T[B]D|T[O]DO|PLACE[H]OLDER' -CaseSensitive:$false
```

Expected: no matches.

- [ ] **Step 5: Commit**

Run secret scan first, then:

```powershell
git add README.md skills/projectflow-agent-eval/SKILL.md skills/projectflow-agent-eval/references/command-guide.md
git commit -m "docs: document AgentEval real-mode config"
```

## Task 5: Final Verification

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

- [ ] **Step 4: Smoke config commands without real keys**

Run:

```powershell
pfae config path
```

Expected: prints the user config path.

Run:

```powershell
pfae config show
```

Expected: if no config exists, exits non-zero with `Run pfae config init`. It must not print secrets.

- [ ] **Step 5: Secret scan staged candidate files**

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

## Self-Review

- Spec coverage: The plan covers user config path, plaintext storage warning, config commands, real-mode first-run setup, precedence via non-overriding environment application, docs, skill updates, tests, lint, and secret scanning.
- Marker scan: No unfinished-work markers are intentionally left in this plan.
- Type consistency: The plan consistently uses `ModelConfig`, `AgentEvalUserConfig`, `config_path`, `load_user_config`, `save_user_config`, `apply_user_config_to_env`, `config_init`, `config_show`, `config_path_command`, and `ensure_real_config`.
