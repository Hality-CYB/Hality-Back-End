from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, computed_field, model_validator
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

    # Banco de dados — variáveis individuais (obrigatórias via .env)
    postgres_host: str
    postgres_port: int
    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    db_echo: bool = False

    diagnostic_provider: str = "mock"

    diagnostic_mock_level: int = Field(
        default=2,
        ge=1,
        le=3,
    )

    diagnostic_mock_scenario: Literal[
        "success",
        "processing",
        "failure",
        "invalid_response",
    ] = "success"

    @computed_field
    @property
    def database_url(self) -> str:
        return (
            "postgresql+asyncpg://"
            f"{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    secret_key: SecretStr
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30

    @model_validator(mode="after")
    def validate_diagnostic_provider(
        self,
    ) -> "Settings":
        environment = self.environment.lower()

        if environment in {"production", "prod"} and self.diagnostic_provider == "mock":
            raise ValueError("DIAGNOSTIC_PROVIDER=mock não pode ser usado em produção.")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
