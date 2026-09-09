import pytest
from pydantic import ValidationError

from app.schemas.conteudo_diagnostico import ConteudoDiagnosticoCreate


def test_criar_dica_com_payload_padronizado() -> None:
    conteudo = ConteudoDiagnosticoCreate(
        tipo="dica",
        titulo="Higiene bucal",
        dados={"tipo_midia": "texto", "corpo": "Escove os dentes após as refeições."},
    )

    assert conteudo.dados == {
        "tipo_midia": "texto",
        "corpo": "Escove os dentes após as refeições.",
    }


def test_criar_protocolo_com_payload_padronizado() -> None:
    conteudo = ConteudoDiagnosticoCreate(
        classificacao_id=None,
        tipo="protocolo",
        titulo="Protocolo de acompanhamento",
        dados={"numero_sessoes": 4, "descricao": "Uma sessão por semana."},
    )

    assert conteudo.dados == {
        "numero_sessoes": 4,
        "descricao": "Uma sessão por semana.",
    }


@pytest.mark.parametrize(
    ("tipo", "dados"),
    [
        ("dica", {"numero_sessoes": 4, "descricao": "Inválido para dica."}),
        ("protocolo", {"tipo_midia": "texto", "corpo": "Inválido para protocolo."}),
    ],
)
def test_rejeita_payload_incompativel_com_tipo(tipo: str, dados: dict) -> None:
    with pytest.raises(ValidationError):
        ConteudoDiagnosticoCreate(tipo=tipo, titulo="Conteúdo", dados=dados)


def test_rejeita_campos_extras_no_payload() -> None:
    with pytest.raises(ValidationError):
        ConteudoDiagnosticoCreate(
            tipo="dica",
            titulo="Conteúdo",
            dados={"tipo_midia": "texto", "corpo": "Texto", "extra": "não permitido"},
        )


@pytest.mark.parametrize(
    "dados",
    [
        {"tipo_midia": "", "corpo": "Texto"},
        {"tipo_midia": "texto", "corpo": ""},
        {"tipo_midia": "texto", "corpo": "Texto", "extra": "não permitido"},
    ],
)
def test_rejeita_dica_com_dados_invalidos(dados: dict) -> None:
    with pytest.raises(ValidationError):
        ConteudoDiagnosticoCreate(tipo="dica", titulo="Conteúdo", dados=dados)


def test_rejeita_protocolo_sem_sessoes_validas() -> None:
    with pytest.raises(ValidationError):
        ConteudoDiagnosticoCreate(
            tipo="protocolo",
            titulo="Conteúdo",
            dados={"numero_sessoes": 0, "descricao": "Descrição"},
        )


def test_mensagem_de_erro_nao_mistura_schemas() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ConteudoDiagnosticoCreate(tipo="dica", titulo="Conteúdo", dados={"corpo": ""})

    mensagem = str(exc_info.value)
    assert "DadosProtocolo" not in mensagem
    assert "numero_sessoes" not in mensagem