from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_name: str
    api_v1_prefix: str
    environment: str
    debug: bool

    cors_origins: list[str]

    postgres_host: str
    postgres_port: int
    postgres_user: str
    postgres_password: str
    postgres_db: str
    db_echo: bool

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
            f"{self.postgres_password}"
            f"@{self.postgres_host}:"
            f"{self.postgres_port}/"
            f"{self.postgres_db}"
        )

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
