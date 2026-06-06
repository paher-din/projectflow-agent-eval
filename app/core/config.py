from pydantic import PositiveFloat, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./data/projectflow.sqlite"
    llm_provider: str = "mock"
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: PositiveFloat = 30.0
    llm_agent_timeout_seconds: PositiveFloat = 120.0
    demo_admin_token: SecretStr | None = None
    semantic_judge_provider: str = "openai-compatible"
    semantic_judge_api_key: SecretStr | None = None
    semantic_judge_base_url: str = ""
    semantic_judge_model: str = "deepseek-v4-flash"
    semantic_judge_timeout_seconds: PositiveFloat = 20.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
