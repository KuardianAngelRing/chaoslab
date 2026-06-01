from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ChaosLab"
    database_url: str = "sqlite:///./chaoslab.db"

    # 외부 시스템 (Slice 1 미사용, 구조만)
    k8s_context: str = ""
    prometheus_url: str = "http://localhost:9090"
    loki_url: str = "http://localhost:3100"

    # AI (Phase 3)
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"
    target_r: float = 0.7


settings = Settings()
