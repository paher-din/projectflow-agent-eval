"""Tests for the AgentEval user config module."""

import os
import json
from pathlib import Path

import pytest

from app.agent_eval.commands.common import CommandError
from app.agent_eval.commands.config import (
    AgentEvalUserConfig,
    ModelConfig,
    apply_user_config_to_env,
    config_agent_add,
    config_agent_list,
    config_agent_show,
    config_agent_use,
    config_init,
    config_judge_add,
    config_judge_list,
    config_judge_show,
    config_judge_use,
    config_path,
    config_path_command,
    config_show,
    ensure_real_config,
    has_real_llm_env,
    load_user_config,
    mask_secret,
    save_user_config,
)


REAL_CONFIG_ENV_KEYS = [
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "SEMANTIC_JUDGE_BASE_URL",
    "SEMANTIC_JUDGE_API_KEY",
    "SEMANTIC_JUDGE_MODEL",
]


@pytest.fixture(autouse=True)
def restore_app_settings() -> None:
    from app.core.config import settings

    snapshot = {
        "llm_provider": settings.llm_provider,
        "llm_base_url": settings.llm_base_url,
        "llm_api_key": settings.llm_api_key,
        "llm_model": settings.llm_model,
        "semantic_judge_provider": settings.semantic_judge_provider,
        "semantic_judge_base_url": settings.semantic_judge_base_url,
        "semantic_judge_api_key": settings.semantic_judge_api_key,
        "semantic_judge_model": settings.semantic_judge_model,
    }
    yield
    for name, value in snapshot.items():
        setattr(settings, name, value)


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
        current_agent="default-agent",
        current_judge="default-judge",
        agent_models={"default-agent": ModelConfig(base_url="https://agent.example/v1", api_key=agent_key, model="agent-model")},
        judge_models={"default-judge": ModelConfig(base_url="https://judge.example/v1", api_key=judge_key, model="judge-model")},
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
        current_agent="default-agent",
        current_judge="default-judge",
        agent_models={"default-agent": ModelConfig(base_url="https://agent.example/v1", api_key=agent_key, model="agent-model")},
        judge_models={"default-judge": ModelConfig(base_url="https://judge.example/v1", api_key=judge_key, model="judge-model")},
    )
    monkeypatch.setenv("LLM_MODEL", "env-agent-model")

    apply_user_config_to_env(config)

    import os
    assert os.environ["LLM_MODEL"] == "env-agent-model"
    assert os.environ["LLM_BASE_URL"] == "https://agent.example/v1"
    assert os.environ["LLM_API_KEY"] == "agent-key"
    assert os.environ["SEMANTIC_JUDGE_BASE_URL"] == "https://judge.example/v1"
    assert os.environ["SEMANTIC_JUDGE_API_KEY"] == "judge-key"
    assert os.environ["SEMANTIC_JUDGE_MODEL"] == "judge-model"


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
            current_agent="default-agent",
            current_judge="default-judge",
            agent_models={"default-agent": ModelConfig(base_url="https://agent.example/v1", api_key=agent_key, model="agent-model")},
            judge_models={"default-judge": ModelConfig(base_url="https://judge.example/v1", api_key=judge_key, model="judge-model")},
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
        "agent-main",
        "https://agent.example/v1",
        "agent-model",
        "judge-main",
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
    assert config.current_agent == "agent-main"
    assert config.current_judge == "judge-main"
    assert config.agent.api_key == "agent-key"
    assert config.judge.model == "judge-model"


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


def test_add_agent_model_does_not_change_judge_models(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    save_user_config(_registry_config(), path)

    config_agent_add("agent-alt", path=path, input_func=_input_values("https://agent2.example/v1", "agent2-model"), getpass_func=_secret_values("agent2-key"))

    loaded = load_user_config(path)
    assert loaded is not None
    assert "agent-alt" in loaded.agent_models
    assert list(loaded.judge_models) == ["judge-main"]


def test_add_agent_model_requires_existing_config(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="Run `pfae config init` first"):
        config_agent_add(
            "agent-alt",
            path=tmp_path / "missing.json",
            input_func=_input_values("https://agent2.example/v1", "agent2-model"),
            getpass_func=_secret_values("agent2-key"),
        )


def test_add_judge_model_does_not_change_agent_models(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    save_user_config(_registry_config(), path)

    config_judge_add("judge-alt", path=path, input_func=_input_values("https://judge2.example/v1", "judge2-model"), getpass_func=_secret_values("judge2-key"))

    loaded = load_user_config(path)
    assert loaded is not None
    assert "judge-alt" in loaded.judge_models
    assert list(loaded.agent_models) == ["agent-main"]


def test_add_judge_model_requires_existing_config(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="Run `pfae config init` first"):
        config_judge_add(
            "judge-alt",
            path=tmp_path / "missing.json",
            input_func=_input_values("https://judge2.example/v1", "judge2-model"),
            getpass_func=_secret_values("judge2-key"),
        )


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


def test_agent_list_marks_active(capsys: pytest.CaptureFixture[str]) -> None:
    config_agent_list(_registry_config())
    captured = capsys.readouterr()
    assert "* agent-main" in captured.out


def test_judge_list_marks_active(capsys: pytest.CaptureFixture[str]) -> None:
    config_judge_list(_registry_config())
    captured = capsys.readouterr()
    assert "* judge-main" in captured.out


def test_agent_show_masks_key(capsys: pytest.CaptureFixture[str]) -> None:
    config_agent_show("agent-main", _registry_config())
    captured = capsys.readouterr()
    assert "agent-model" in captured.out
    assert "agent-key" not in captured.out


def test_agent_show_unknown_raises_error() -> None:
    with pytest.raises(CommandError, match="not found"):
        config_agent_show("unknown", _registry_config())


def test_judge_show_masks_key(capsys: pytest.CaptureFixture[str]) -> None:
    config_judge_show("judge-main", _registry_config())
    captured = capsys.readouterr()
    assert "judge-model" in captured.out
    assert "judge-key" not in captured.out


def test_judge_show_unknown_raises_error() -> None:
    with pytest.raises(CommandError, match="not found"):
        config_judge_show("unknown", _registry_config())


def test_has_real_llm_env_requires_agent_and_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in REAL_CONFIG_ENV_KEYS:
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
    for key in REAL_CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "config.json"
    agent_key = "agent-key"
    judge_key = "judge-key"
    save_user_config(
        AgentEvalUserConfig(
            current_agent="default-agent",
            current_judge="default-judge",
            agent_models={"default-agent": ModelConfig(base_url="https://agent.example/v1", api_key=agent_key, model="agent-model")},
            judge_models={"default-judge": ModelConfig(base_url="https://judge.example/v1", api_key=judge_key, model="judge-model")},
        ),
        path,
    )

    ensure_real_config(path=path, interactive=False)

    assert os.environ["LLM_MODEL"] == "agent-model"
    assert os.environ["SEMANTIC_JUDGE_MODEL"] == "judge-model"


def test_ensure_real_config_fails_noninteractive_without_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in REAL_CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(CommandError, match="No real LLM config found"):
        ensure_real_config(path=tmp_path / "missing.json", interactive=False)


def test_apply_user_config_uses_selected_agent_and_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in REAL_CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
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

    assert os.environ["LLM_BASE_URL"] == "https://agent2.example/v1"
    assert os.environ["LLM_MODEL"] == "agent2-model"
    assert os.environ["LLM_API_KEY"] == "agent2-key"
    assert os.environ["SEMANTIC_JUDGE_BASE_URL"] == "https://judge2.example/v1"
    assert os.environ["SEMANTIC_JUDGE_MODEL"] == "judge2-model"
    assert os.environ["SEMANTIC_JUDGE_API_KEY"] == "judge2-key"
