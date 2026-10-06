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
