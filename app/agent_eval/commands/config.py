from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from getpass import getpass
from pathlib import Path
from typing import Callable

from pydantic import SecretStr

from app.agent_eval.commands.common import CommandError


@dataclass(frozen=True)
class ModelConfig:
    base_url: str
    api_key: str
    model: str


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
            raise CommandError(
                f"Current Agent model not found: {self.current_agent}. "
                f"Run `pfae config agent list` to see available entries."
            ) from exc

    @property
    def judge(self) -> ModelConfig:
        try:
            return self.judge_models[self.current_judge]
        except KeyError as exc:
            raise CommandError(
                f"Current Judge model not found: {self.current_judge}. "
                f"Run `pfae config judge list` to see available entries."
            ) from exc


def config_path(*, platform_name: str | None = None) -> Path:
    selected_platform = platform_name or os.name
    if selected_platform == "nt":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return root / "ProjectFlow-AgentEval" / "config.json"
    root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "projectflow-agent-eval" / "config.json"


def _model_config_map(raw: dict[str, object]) -> dict[str, ModelConfig]:
    return {name: ModelConfig(**value) for name, value in raw.items()}


def load_user_config(path: Path | None = None) -> AgentEvalUserConfig | None:
    selected_path = path or config_path()
    if not selected_path.exists():
        return None
    try:
        raw = json.loads(selected_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CommandError(f"Malformed user config: {selected_path}: {exc}") from exc
    try:
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


def apply_env_to_runtime_settings() -> None:
    """Refresh already-imported app settings from process env.

    `app.core.config.settings` is instantiated at import time. The CLI can load
    user config after the runner has already imported settings, so real-mode
    setup must update both os.environ and the in-memory settings object.
    """
    from app.core.config import settings as app_settings

    if os.environ.get("LLM_PROVIDER"):
        app_settings.llm_provider = os.environ["LLM_PROVIDER"]
    if os.environ.get("LLM_BASE_URL"):
        app_settings.llm_base_url = os.environ["LLM_BASE_URL"]
    if os.environ.get("LLM_API_KEY"):
        app_settings.llm_api_key = SecretStr(os.environ["LLM_API_KEY"])
    if os.environ.get("LLM_MODEL"):
        app_settings.llm_model = os.environ["LLM_MODEL"]
    if os.environ.get("SEMANTIC_JUDGE_PROVIDER"):
        app_settings.semantic_judge_provider = os.environ["SEMANTIC_JUDGE_PROVIDER"]
    if os.environ.get("SEMANTIC_JUDGE_BASE_URL"):
        app_settings.semantic_judge_base_url = os.environ["SEMANTIC_JUDGE_BASE_URL"]
    if os.environ.get("SEMANTIC_JUDGE_API_KEY"):
        app_settings.semantic_judge_api_key = SecretStr(
            os.environ["SEMANTIC_JUDGE_API_KEY"]
        )
    if os.environ.get("SEMANTIC_JUDGE_MODEL"):
        app_settings.semantic_judge_model = os.environ["SEMANTIC_JUDGE_MODEL"]


def _settings_have_real_config() -> bool:
    from app.core.config import settings as app_settings

    return all(
        [
            bool(app_settings.llm_base_url),
            bool(app_settings.llm_api_key),
            bool(app_settings.llm_model),
            bool(app_settings.semantic_judge_base_url),
            bool(app_settings.semantic_judge_api_key),
            bool(app_settings.semantic_judge_model),
        ]
    )


def _env_has_real_config() -> bool:
    required = [
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
        "SEMANTIC_JUDGE_BASE_URL",
        "SEMANTIC_JUDGE_API_KEY",
        "SEMANTIC_JUDGE_MODEL",
    ]
    return all(bool(os.environ.get(key)) for key in required)


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
    agent_name = _prompt_required("Agent model name", input_func=input_func)
    agent = ModelConfig(
        base_url=_prompt_required("Agent LLM base URL", input_func=input_func),
        api_key=_prompt_secret("Agent LLM API key", getpass_func=getpass_func),
        model=_prompt_required("Agent LLM model", input_func=input_func),
    )
    judge_name = _prompt_required("Judge model name", input_func=input_func)
    judge = ModelConfig(
        base_url=_prompt_required("Judge LLM base URL", input_func=input_func),
        api_key=_prompt_secret("Judge LLM API key", getpass_func=getpass_func),
        model=_prompt_required("Judge LLM model", input_func=input_func),
    )
    return AgentEvalUserConfig(
        current_agent=agent_name,
        current_judge=judge_name,
        agent_models={agent_name: agent},
        judge_models={judge_name: judge},
    )


def config_path_command(*, path: Path | None = None) -> int:
    print(path or config_path())
    return 0


def config_show(*, path: Path | None = None) -> int:
    selected_path = path or config_path()
    config = load_user_config(selected_path)
    if config is None:
        raise CommandError(f"No user config found at {selected_path}. Run `pfae config init`.")
    print(f"Config path: {selected_path}")
    print(f"Current Agent model: {config.current_agent}")
    agent_cfg = config.agent
    print(f"  base_url: {agent_cfg.base_url}")
    print(f"  model: {agent_cfg.model}")
    print(f"  api_key: {mask_secret(agent_cfg.api_key)}")
    print(f"Current Judge model: {config.current_judge}")
    judge_cfg = config.judge
    print(f"  base_url: {judge_cfg.base_url}")
    print(f"  model: {judge_cfg.model}")
    print(f"  api_key: {mask_secret(judge_cfg.api_key)}")
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


def _prompt_model_config(
    role: str,
    *,
    input_func: Callable[[str], str] = input,
    getpass_func: Callable[[str], str] = getpass,
) -> ModelConfig:
    return ModelConfig(
        base_url=_prompt_required(f"{role} base URL", input_func=input_func),
        api_key=_prompt_secret(f"{role} API key", getpass_func=getpass_func),
        model=_prompt_required(f"{role} model", input_func=input_func),
    )


def _load_existing_config(path: Path | None) -> AgentEvalUserConfig:
    config = load_user_config(path)
    if config is None:
        raise CommandError("No user config found. Run `pfae config init` first.")
    return config


def config_agent_add(
    name: str,
    *,
    path: Path | None = None,
    input_func: Callable[[str], str] = input,
    getpass_func: Callable[[str], str] = getpass,
) -> int:
    config = _load_existing_config(path)
    model = _prompt_model_config("Agent LLM", input_func=input_func, getpass_func=getpass_func)
    config = AgentEvalUserConfig(
        current_agent=config.current_agent,
        current_judge=config.current_judge,
        agent_models={**config.agent_models, name: model},
        judge_models=config.judge_models,
    )
    save_user_config(config, path)
    print(f"Saved Agent model: {name}")
    return 0


def config_judge_add(
    name: str,
    *,
    path: Path | None = None,
    input_func: Callable[[str], str] = input,
    getpass_func: Callable[[str], str] = getpass,
) -> int:
    config = _load_existing_config(path)
    model = _prompt_model_config("Judge LLM", input_func=input_func, getpass_func=getpass_func)
    config = AgentEvalUserConfig(
        current_agent=config.current_agent,
        current_judge=config.current_judge,
        agent_models=config.agent_models,
        judge_models={**config.judge_models, name: model},
    )
    save_user_config(config, path)
    print(f"Saved Judge model: {name}")
    return 0


def config_agent_use(name: str, *, path: Path | None = None) -> int:
    config = _load_existing_config(path)
    if name not in config.agent_models:
        raise CommandError(f"Agent model not found: {name}. Run `pfae config agent list` to see available entries.")
    config = AgentEvalUserConfig(name, config.current_judge, config.agent_models, config.judge_models)
    save_user_config(config, path)
    print(f"Switched to Agent model: {name}")
    return 0


def config_judge_use(name: str, *, path: Path | None = None) -> int:
    config = _load_existing_config(path)
    if name not in config.judge_models:
        raise CommandError(f"Judge model not found: {name}. Run `pfae config judge list` to see available entries.")
    config = AgentEvalUserConfig(config.current_agent, name, config.agent_models, config.judge_models)
    save_user_config(config, path)
    print(f"Switched to Judge model: {name}")
    return 0


def config_agent_list(config: AgentEvalUserConfig | None = None) -> int:
    if config is None:
        config = load_user_config()
    if config is None:
        print("No Agent models configured.")
        return 0
    for name in config.agent_models:
        marker = "* " if name == config.current_agent else "  "
        print(f"{marker}{name}")
    return 0


def config_judge_list(config: AgentEvalUserConfig | None = None) -> int:
    if config is None:
        config = load_user_config()
    if config is None:
        print("No Judge models configured.")
        return 0
    for name in config.judge_models:
        marker = "* " if name == config.current_judge else "  "
        print(f"{marker}{name}")
    return 0


def _show_model_entry(name: str, model: ModelConfig) -> None:
    print(f"  name: {name}")
    print(f"  base_url: {model.base_url}")
    print(f"  model: {model.model}")
    print(f"  api_key: {mask_secret(model.api_key)}")


def config_agent_show(name: str, config: AgentEvalUserConfig | None = None) -> int:
    if config is None:
        config = load_user_config()
    if config is None or name not in config.agent_models:
        raise CommandError(f"Agent model not found: {name}. Run `pfae config agent list` to see available entries.")
    _show_model_entry(name, config.agent_models[name])
    return 0


def config_judge_show(name: str, config: AgentEvalUserConfig | None = None) -> int:
    if config is None:
        config = load_user_config()
    if config is None or name not in config.judge_models:
        raise CommandError(f"Judge model not found: {name}. Run `pfae config judge list` to see available entries.")
    _show_model_entry(name, config.judge_models[name])
    return 0


def has_real_llm_env() -> bool:
    return _env_has_real_config() or _settings_have_real_config()


def ensure_real_config(*, path: Path | None = None, interactive: bool = True) -> None:
    if _env_has_real_config():
        apply_env_to_runtime_settings()
        return
    if _settings_have_real_config():
        return
    selected_path = path or config_path()
    config = load_user_config(selected_path)
    if config is not None:
        apply_user_config_to_env(config)
        apply_env_to_runtime_settings()
        return
    if not interactive:
        raise CommandError(f"No real LLM config found. Run `pfae config init` to create {selected_path}.")
    print("No real LLM config found. Starting first-run setup.")
    config_init(path=selected_path)
    config = load_user_config(selected_path)
    if config is None:
        raise CommandError("Configuration was canceled.")
    apply_user_config_to_env(config)
    apply_env_to_runtime_settings()
