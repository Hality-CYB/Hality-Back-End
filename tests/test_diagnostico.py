import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import diagnostico_service

PACIENTE_STUB_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_OUTRO_PACIENTE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _anamnese(paciente_id=PACIENTE_STUB_ID):
    return SimpleNamespace(
        id=128,
        paciente_id=paciente_id,
        data_preenchimento=datetime.now(UTC),
        respostas=[],
    )


def _diagnostico(
    paciente_id=PACIENTE_STUB_ID,
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
        score=None,
        provider=None,
        model_version=None,
        erro=None,
        data_envio=None,
        data_processamento=None,
        profissional_revisor_id=None,
        data_revisao=None,
        observacoes_revisao=None,
    )


def test_criar_diagnostico(monkeypatch):
    diagnostico = _diagnostico()

    monkeypatch.setattr(
        diagnostico_service.anamnese_queries,
        "buscar_por_id",
        AsyncMock(return_value=_anamnese()),
    )
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
        "_processar_com_provider",
        AsyncMock(return_value=diagnostico),
    )
    monkeypatch.setattr(
        diagnostico_service,
        "get_settings",
        lambda: SimpleNamespace(api_v1_prefix="/api/v1"),
    )

    resultado = asyncio.run(
        diagnostico_service.criar_diagnostico(
            db=AsyncMock(),
            paciente_id=PACIENTE_STUB_ID,
            anamnese_id=128,
            imagem=b"imagem",
            content_type="image/jpeg",
            parametros_captura={},
        )
    )

    assert resultado["id"] == 4
    assert resultado["status"] == "processando"
    assert resultado["anamnese_id"] == 128


def test_anamnese_de_outro_paciente(monkeypatch):
    monkeypatch.setattr(
        diagnostico_service.anamnese_queries,
        "buscar_por_id",
        AsyncMock(return_value=_anamnese(paciente_id=_OUTRO_PACIENTE_ID)),
    )

    with pytest.raises(diagnostico_service.AnamneseNaoEncontradaError):
        asyncio.run(
            diagnostico_service.criar_diagnostico(
                db=AsyncMock(),
                paciente_id=PACIENTE_STUB_ID,
                anamnese_id=128,
                imagem=b"imagem",
                content_type="image/jpeg",
                parametros_captura={},
            )
        )


def test_anamnese_ja_utilizada(monkeypatch):
    monkeypatch.setattr(
        diagnostico_service.anamnese_queries,
        "buscar_por_id",
        AsyncMock(return_value=_anamnese()),
    )
    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "buscar_por_anamnese",
        AsyncMock(return_value=_diagnostico()),
    )

    with pytest.raises(diagnostico_service.AnamneseJaUtilizadaError):
        asyncio.run(
            diagnostico_service.criar_diagnostico(
                db=AsyncMock(),
                paciente_id=PACIENTE_STUB_ID,
                anamnese_id=128,
                imagem=b"imagem",
                content_type="image/jpeg",
                parametros_captura={},
            )
        )


def test_retry_diagnostico_com_falha(monkeypatch):
    diagnostico = _diagnostico(status="falha")
    processado = _diagnostico(status="concluido")

    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "buscar_por_id",
        AsyncMock(return_value=diagnostico),
    )
    monkeypatch.setattr(
        diagnostico_service.anamnese_queries,
        "buscar_por_id",
        AsyncMock(return_value=_anamnese()),
    )
    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "listar_imagens",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    url_arquivo="/imagem.jpg",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        diagnostico_service,
        "_processar_com_provider",
        AsyncMock(return_value=processado),
    )

    resultado = asyncio.run(
        diagnostico_service.retry_diagnostico(
            db=AsyncMock(),
            paciente_id=PACIENTE_STUB_ID,
            diagnostico_id=4,
        )
    )

    assert resultado["id"] == 4
    assert resultado["status"] == "concluido"
    assert resultado["anamnese_id"] == 128


def test_retry_so_permite_diagnostico_com_falha(
    monkeypatch,
):
    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "buscar_por_id",
        AsyncMock(return_value=_diagnostico(status="concluido")),
    )

    with pytest.raises(
        diagnostico_service.DiagnosticoRetryInvalidoError,
    ):
        asyncio.run(
            diagnostico_service.retry_diagnostico(
                db=AsyncMock(),
                paciente_id=PACIENTE_STUB_ID,
                diagnostico_id=4,
            )
        )


def test_processar_com_provider_success(monkeypatch):
    diagnostico = _diagnostico()

    monkeypatch.setattr(
        diagnostico_service,
        "get_settings",
        lambda: SimpleNamespace(
            diagnostic_provider="mock",
            diagnostic_mock_level=2,
            diagnostic_mock_scenario="success",
        ),
    )
    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "buscar_classificacao_por_ordem",
        AsyncMock(return_value=SimpleNamespace(id=2)),
    )

    async def salvar_resultado(
        db,
        diagnostico,
        classificacao_id,
        provider,
        model_version,
        score,
        confianca_ia,
        data_processamento,
    ):
        diagnostico.classificacao_id = classificacao_id
        diagnostico.status = "concluido"
        diagnostico.provider = provider
        diagnostico.model_version = model_version
        diagnostico.score = score
        diagnostico.confianca_ia = confianca_ia
        diagnostico.data_processamento = data_processamento
        return diagnostico

    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "salvar_resultado",
        salvar_resultado,
    )

    resultado = asyncio.run(
        diagnostico_service._processar_com_provider(
            db=AsyncMock(),
            diagnostico=diagnostico,
            anamnese=_anamnese(),
            url_arquivo="/imagem.jpg",
        )
    )

    assert resultado.status == "concluido"
    assert resultado.classificacao_id == 2
    assert resultado.provider == "mock"
    assert resultado.model_version == "mock-v1"


@pytest.mark.parametrize(
    ("scenario", "status", "model_version"),
    [
        ("processing", "processando", "mock-v1"),
        ("failure", "falha", "mock-v1"),
        ("invalid_response", "falha", "unknown"),
    ],
)
def test_processar_com_provider_cenarios(
    monkeypatch,
    scenario,
    status,
    model_version,
):
    diagnostico = _diagnostico()

    monkeypatch.setattr(
        diagnostico_service,
        "get_settings",
        lambda: SimpleNamespace(
            diagnostic_provider="mock",
            diagnostic_mock_level=2,
            diagnostic_mock_scenario=scenario,
        ),
    )

    async def marcar_processando(
        db,
        diagnostico,
        provider,
        model_version,
    ):
        diagnostico.status = "processando"
        diagnostico.provider = provider
        diagnostico.model_version = model_version
        return diagnostico

    async def marcar_falha(
        db,
        diagnostico,
        erro,
        provider,
        model_version,
        data_processamento,
    ):
        diagnostico.status = "falha"
        diagnostico.erro = erro
        diagnostico.provider = provider
        diagnostico.model_version = model_version
        diagnostico.data_processamento = data_processamento
        return diagnostico

    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "marcar_processando",
        marcar_processando,
    )
    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "marcar_falha",
        marcar_falha,
    )

    resultado = asyncio.run(
        diagnostico_service._processar_com_provider(
            db=AsyncMock(),
            diagnostico=diagnostico,
            anamnese=_anamnese(),
            url_arquivo="/imagem.jpg",
        )
    )

    assert resultado.status == status
    assert resultado.model_version == model_version

    if status == "falha":
        assert resultado.erro == diagnostico_service.ERRO_PROCESSAMENTO
