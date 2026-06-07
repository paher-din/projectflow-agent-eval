"""Tests for the AgentEval user config module."""

from pathlib import Path

import pytest

from app.agent_eval.commands.common import CommandError
from app.agent_eval.commands.config import (
    AgentEvalUserConfig,
    ModelConfig,
    apply_user_config_to_env,
    config_init,
    config_path,
    config_path_command,
    config_show,
    ensure_real_config,
    has_real_llm_env,
    load_user_config,
    mask_secret,
    save_user_config,
)


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

    import os
    assert os.environ["LLM_MODEL"] == "agent-model"
    assert os.environ["SEMANTIC_JUDGE_MODEL"] == "judge-model"


def test_ensure_real_config_fails_noninteractive_without_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in [
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
        "SEMANTIC_JUDGE_BASE_URL",
        "SEMANTIC_JUDGE_API_KEY",
        "SEMANTIC_JUDGE_MODEL",
    ]:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(CommandError, match="No real LLM config found"):
        ensure_real_config(path=tmp_path / "missing.json", interactive=False)
