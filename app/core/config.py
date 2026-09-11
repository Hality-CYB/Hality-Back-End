from functools import lru_cache

from pydantic import SecretStr, computed_field
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

    @computed_field
    @property
    def database_url(self) -> str:
        """Monta a URL de conexão asyncpg a partir das variáveis individuais."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # JWT — obrigatório via .env (ex.: openssl rand -hex 32)
    secret_key: SecretStr
    access_token_expire_minutes: int = 60 * 24  # 24 horas


@lru_cache
def get_settings() -> Settings:
    return Settings()
