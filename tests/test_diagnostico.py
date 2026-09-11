import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import diagnostico_mock, diagnostico_service


class AnamneseRepoFake:
    def __init__(self, anamnese=None):
        self.anamnese = anamnese

    def obter_por_id(self, anamnese_id):
        return self.anamnese


def _anamnese(paciente_id=1):
    return SimpleNamespace(
        id=128,
        paciente_id=paciente_id,
        data_preenchimento=datetime.now(UTC),
        respostas=[],
    )


def _diagnostico(
    paciente_id=1,
    status="processando",
):
    return SimpleNamespace(
        id=4,
        paciente_id=paciente_id,
        anamnese_id=128,
        status=status,
        data_diagnostico=datetime.now(UTC),
        classificacao_id=None,
        escala_saburra=None,
        confianca_ia=None,
        profissional_revisor_id=None,
        data_revisao=None,
        observacoes_revisao=None,
        nivel_corrigido=False,
        erro=None,
    )


def test_criar_diagnostico(monkeypatch):
    diagnostico = _diagnostico()

    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "buscar_por_anamnese",
        AsyncMock(return_value=None),
    )

    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "inserir",
        AsyncMock(return_value=diagnostico),
    )

    monkeypatch.setattr(
        diagnostico_service.diagnostico_storage,
        "salvar",
        AsyncMock(return_value="/imagem.jpg"),
    )

    monkeypatch.setattr(
        diagnostico_service,
        "get_settings",
        lambda: SimpleNamespace(api_v1_prefix="/api/v1"),
    )

    resultado = asyncio.run(
        diagnostico_service.criar_diagnostico(
            db=AsyncMock(),
            repo_anamnese=AnamneseRepoFake(_anamnese()),
            paciente_id=1,
            anamnese_id=128,
            imagem=b"imagem",
            content_type="image/jpeg",
            parametros_captura={},
        )
    )

    assert resultado["id"] == 4
    assert resultado["status"] == "processando"
    assert resultado["anamnese_id"] == 128


def test_anamnese_de_outro_paciente():
    with pytest.raises(diagnostico_service.AnamneseNaoEncontradaError):
        asyncio.run(
            diagnostico_service.criar_diagnostico(
                db=AsyncMock(),
                repo_anamnese=AnamneseRepoFake(_anamnese(paciente_id=2)),
                paciente_id=1,
                anamnese_id=128,
                imagem=b"imagem",
                content_type="image/jpeg",
                parametros_captura={},
            )
        )


def test_anamnese_ja_utilizada(monkeypatch):
    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "buscar_por_anamnese",
        AsyncMock(return_value=_diagnostico()),
    )

    with pytest.raises(diagnostico_service.AnamneseJaUtilizadaError):
        asyncio.run(
            diagnostico_service.criar_diagnostico(
                db=AsyncMock(),
                repo_anamnese=AnamneseRepoFake(_anamnese()),
                paciente_id=1,
                anamnese_id=128,
                imagem=b"imagem",
                content_type="image/jpeg",
                parametros_captura={},
            )
        )


def test_mock_cobre_os_tres_niveis():
    assert diagnostico_mock.resultado_para(1).ordem_classificacao == 1

    assert diagnostico_mock.resultado_para(2).ordem_classificacao == 2

    assert diagnostico_mock.resultado_para(3).ordem_classificacao == 3
