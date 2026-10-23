import pytest
from pydantic import ValidationError

from app.core.config import Settings

CONFIGURACAO_MINIMA = {
    "postgres_host": "localhost",
    "postgres_port": 5432,
    "postgres_user": "hality",
    "postgres_password": "senha-super-secreta",
    "postgres_db": "hality",
    "secret_key": "token-super-secreto",
}


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("true", True),
        ("FALSE", False),
        ("yes", True),
        ("No", False),
        ("on", True),
        ("OFF", False),
        ("1", True),
        ("0", False),
    ],
)
def test_debug_aceita_apenas_representacoes_documentadas(valor: str, esperado: bool) -> None:
    settings = Settings(**CONFIGURACAO_MINIMA, debug=valor, _env_file=None)

    assert settings.debug is esperado


def test_debug_invalido_falha_com_mensagem_clara() -> None:
    with pytest.raises(ValidationError, match="DEBUG deve ser booleano"):
        Settings(**CONFIGURACAO_MINIMA, debug="WARN", _env_file=None)


def test_configuracao_serializada_nao_expoe_url_com_senha() -> None:
    settings = Settings(**CONFIGURACAO_MINIMA, _env_file=None)

    assert "database_url" not in settings.model_dump()
    assert "senha-super-secreta" not in repr(settings)
    assert "token-super-secreto" not in repr(settings)


def test_producao_exige_remetente_e_url_publica() -> None:
    with pytest.raises(ValidationError, match="EMAIL_PROVIDER deve ser resend"):
        Settings(**CONFIGURACAO_MINIMA, environment="production", _env_file=None)

    with pytest.raises(ValidationError, match="HTTPS público"):
        Settings(
            **CONFIGURACAO_MINIMA,
            environment="production",
            email_provider="resend",
            resend_api_key="re_teste",
            resend_from_email="CYB <notificacoes@example.com>",
            _env_file=None,
        )


def test_remetente_de_teste_exige_destinatario_limitado() -> None:
    with pytest.raises(ValidationError, match="RESEND_TEST_RECIPIENT"):
        Settings(
            **CONFIGURACAO_MINIMA,
            email_provider="resend",
            resend_api_key="re_teste",
            resend_from_email="CYB <onboarding@resend.dev>",
            _env_file=None,
        )


@pytest.mark.parametrize(
    ("environment", "email_provider", "resend_from_email"),
    [
        ("development", "noop", None),
        ("development", "resend", "CYB <notificacoes@example.com>"),
        ("test", "resend", "CYB <onboarding@resend.dev>"),
    ],
)
def test_destinatario_de_teste_exige_modo_local_e_remetente_sandbox(
    environment: str, email_provider: str, resend_from_email: str | None
) -> None:
    with pytest.raises(ValidationError, match="RESEND_TEST_RECIPIENT só é permitido"):
        Settings(
            **CONFIGURACAO_MINIMA,
            environment=environment,
            email_provider=email_provider,
            resend_api_key="re_teste",
            resend_from_email=resend_from_email,
            resend_test_recipient="conta@example.com",
            _env_file=None,
        )


def test_dominio_verificado_nao_exige_destinatario_de_teste() -> None:
    settings = Settings(
        **CONFIGURACAO_MINIMA,
        email_provider="resend",
        resend_api_key="re_teste",
        resend_from_email="CYB <notificacoes@example.com>",
        _env_file=None,
    )

    assert settings.resend_test_recipient is None


def test_producao_aceita_remetente_de_dominio_proprio() -> None:
    settings = Settings(
        **CONFIGURACAO_MINIMA,
        environment="production",
        email_provider="resend",
        resend_api_key="re_teste",
        resend_from_email="CYB <notificacoes@example.com>",
        identity_token_base_url="https://app.example.com",
        resend_test_recipient=None,
        _env_file=None,
    )

    assert settings.environment == "production"
    assert settings.resend_test_recipient is None
