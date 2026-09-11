from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_name: str = "hality-back"
    api_v1_prefix: str = "/api/v1"
    environment: str = "development"
    debug: bool = True

    cors_origins: list[str] = ["http://localhost:3000"]

    # Banco de dados — obrigatório via .env
    database_url: SecretStr

    # JWT — obrigatório via .env (ex.: openssl rand -hex 32)
    secret_key: SecretStr
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 horas


@lru_cache
def get_settings() -> Settings:
    return Settings()
