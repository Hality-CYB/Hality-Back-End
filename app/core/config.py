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
    identity_token_expire_minutes: int = 60
    identity_token_base_url: str = "http://localhost:3000"
    email_provider: str = "noop"
    identity_recovery_rate_limit: int = 5
    identity_recovery_rate_window_seconds: int = 60
    identity_worker_poll_seconds: int = 5

    # Modelo de inferência (API hality-ai). Vazio/None = usa o mock de
    # desenvolvimento (diagnostico_mock). No compose é o nome do serviço na rede
    # interna (http://hality-ai:8000); fora do Docker, http://localhost:8000.
    hality_ai_url: str | None = None
    # A API carrega os modelos e roda 5 passagens por foto; dá folga ao timeout.
    hality_ai_timeout_seconds: float = 30.0

    # Login com Google (US-012). Tudo opcional: sem as quatro variáveis o fluxo
    # fica desligado (503) e o restante da API não é afetado. O client secret
    # só existe aqui, no backend — nunca vai para o frontend.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    # URL do callback do BACKEND, a mesma cadastrada no console do Google.
    google_redirect_uri: str | None = None
    # Para onde o backend devolve o navegador ao fim do callback (com `code` de
    # troca de uso único ou `erro`). Fixa em configuração: nunca vem do request.
    google_frontend_redirect_url: str | None = None
    # Rate limit do GET /auth/google/authorize (público, grava um fluxo por chamada),
    # por IP do cliente, sobre a mesma tabela do rate limit de identidade.
    google_authorize_rate_limit: int = 20
    google_authorize_rate_window_seconds: int = 60

    @property
    def google_configurado(self) -> bool:
        return bool(
            self.google_client_id
            and self.google_client_secret
            and self.google_client_secret.get_secret_value()
            and self.google_redirect_uri
            and self.google_frontend_redirect_url
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
