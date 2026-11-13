"""Atraso do mock: a leitura seguinte conclui ou continua em processando."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import get_settings
from app.schemas.diagnostico import StatusDiagnostico
from app.services import diagnostico_mock


def _fixar_atraso(monkeypatch: pytest.MonkeyPatch, segundos: float) -> None:
    monkeypatch.setattr(get_settings(), "mock_processing_seconds", segundos)


def _diagnostico(*, idade: timedelta) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        status=StatusDiagnostico.PROCESSANDO,
        data_diagnostico=datetime.now(UTC) - idade,
    )


def _mockar_conclusao(monkeypatch: pytest.MonkeyPatch) -> tuple[AsyncMock, AsyncMock]:
    buscar = AsyncMock(return_value=SimpleNamespace(id=7))
    concluir = AsyncMock(side_effect=lambda db, diagnostico, **kwargs: diagnostico)
    monkeypatch.setattr(
        diagnostico_mock.diagnostico_queries,
        "buscar_classificacao_por_ordem",
        buscar,
    )
    monkeypatch.setattr(diagnostico_mock.diagnostico_queries, "concluir_mock", concluir)
    return buscar, concluir


@pytest.mark.asyncio
async def test_atraso_zero_conclui_na_leitura_imediata(monkeypatch: pytest.MonkeyPatch) -> None:
    _fixar_atraso(monkeypatch, 0)
    diagnostico = _diagnostico(idade=timedelta(0))
    buscar, concluir = _mockar_conclusao(monkeypatch)

    await diagnostico_mock.processar_se_necessario(AsyncMock(), diagnostico)

    buscar.assert_awaited_once()
    concluir.assert_awaited_once()


@pytest.mark.asyncio
async def test_atraso_configurado_so_conclui_a_partir_do_limite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixar_atraso(monkeypatch, 1)

    recente = _diagnostico(idade=timedelta(seconds=0.5))
    buscar_recente, concluir_recente = _mockar_conclusao(monkeypatch)

    await diagnostico_mock.processar_se_necessario(AsyncMock(), recente)

    buscar_recente.assert_not_awaited()
    concluir_recente.assert_not_awaited()
    assert recente.status == StatusDiagnostico.PROCESSANDO

    no_limite = _diagnostico(idade=timedelta(seconds=1))
    buscar_limite, concluir_limite = _mockar_conclusao(monkeypatch)

    await diagnostico_mock.processar_se_necessario(AsyncMock(), no_limite)

    buscar_limite.assert_awaited_once()
    concluir_limite.assert_awaited_once()


@pytest.mark.asyncio
async def test_data_no_futuro_continua_processando_mesmo_com_atraso_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixar_atraso(monkeypatch, 0)
    diagnostico = _diagnostico(idade=timedelta(hours=-1))
    buscar, concluir = _mockar_conclusao(monkeypatch)

    await diagnostico_mock.processar_se_necessario(AsyncMock(), diagnostico)

    buscar.assert_not_awaited()
    concluir.assert_not_awaited()
    assert diagnostico.status == StatusDiagnostico.PROCESSANDO
