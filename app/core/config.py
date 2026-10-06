from functools import lru_cache

from pydantic import SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BOOLEANOS_VERDADEIROS = {"1", "true", "yes", "on"}
_BOOLEANOS_FALSOS = {"0", "false", "no", "off"}


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

    @field_validator("debug", "db_echo", mode="before")
    @classmethod
    def validar_booleanos_de_ambiente(cls, valor: object, info: ValidationInfo) -> bool:
        """Aceita somente representações booleanas documentadas nas variáveis de ambiente."""
        if isinstance(valor, bool):
            return valor
        if isinstance(valor, int) and valor in (0, 1):
            return bool(valor)
        if isinstance(valor, str):
            normalizado = valor.strip().lower()
            if normalizado in _BOOLEANOS_VERDADEIROS:
                return True
            if normalizado in _BOOLEANOS_FALSOS:
                return False

        nome = info.field_name.upper()
        raise ValueError(f"{nome} deve ser booleano: use true/false, 1/0, yes/no ou on/off")

    @property
    def database_url(self) -> str:
        """Monta a URL asyncpg sem incluí-la em repr/model_dump, pois contém a senha."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    secret_key: SecretStr
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
