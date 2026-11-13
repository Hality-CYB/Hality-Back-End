"""Mapeamento veredito da API -> classificação/saburra do diagnóstico.

Testa só a função pura `_mapear`; o fluxo com banco (chamada à API, persistência
e falhas) é coberto pela suíte de diagnóstico que usa Postgres real.
"""

import pytest

from app.services.diagnostico_provider import (
    CLASSIFICACAO_INDICIO_FORTE,
    CLASSIFICACAO_INDICIO_LEVE,
    CLASSIFICACAO_SEM_INDICIO,
    LIMIAR_INDICIO_FORTE,
    _mapear,
)
from app.services.hality_ai_client import ResultadoIA


def _resultado(veredito: str, probabilidade: float | None) -> ResultadoIA:
    return ResultadoIA(
        veredito=veredito,
        probabilidade=probabilidade,
        area_lingua=0.4,
        nitidez=30.0,
        motivo="",
        tempo_ms=100,
    )


def test_sem_indicio_vira_halito_normal() -> None:
    mapeado = _mapear(_resultado("sem_indicio", 0.12))

    assert mapeado.classificacao_codigo == CLASSIFICACAO_SEM_INDICIO
    assert mapeado.confianca_ia == 0.12
    assert mapeado.escala_saburra == 12


def test_indicio_fraco_vira_halitose_intima() -> None:
    mapeado = _mapear(_resultado("indicio", 0.60))

    assert mapeado.classificacao_codigo == CLASSIFICACAO_INDICIO_LEVE
    assert mapeado.escala_saburra == 60


def test_indicio_forte_vira_mau_halito_social() -> None:
    mapeado = _mapear(_resultado("indicio", 0.88))

    assert mapeado.classificacao_codigo == CLASSIFICACAO_INDICIO_FORTE
    assert mapeado.escala_saburra == 88


def test_limiar_e_inclusivo_no_grau_forte() -> None:
    mapeado = _mapear(_resultado("indicio", LIMIAR_INDICIO_FORTE))

    assert mapeado.classificacao_codigo == CLASSIFICACAO_INDICIO_FORTE


def test_probabilidade_ausente_nao_quebra_e_fica_sem_saburra() -> None:
    mapeado = _mapear(_resultado("indicio", None))

    # Sem probabilidade, cai no grau leve e não inventa escala de saburra.
    assert mapeado.classificacao_codigo == CLASSIFICACAO_INDICIO_LEVE
    assert mapeado.escala_saburra is None
    assert mapeado.confianca_ia is None


@pytest.mark.asyncio
async def test_ler_imagem_le_pelo_storage(storage_local_isolado, monkeypatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.services import diagnostico_provider, storage

    await storage.atual().salvar("diagnosticos/abc.png", b"bytes", "image/png")
    imagens = [
        SimpleNamespace(url_arquivo="/api/v1/diagnosticos/imagens/abc.png", content_type=None)
    ]
    monkeypatch.setattr(
        diagnostico_provider.diagnostico_queries, "listar_imagens", AsyncMock(return_value=imagens)
    )

    lida = await diagnostico_provider._ler_imagem(AsyncMock(), SimpleNamespace(id=1))

    assert lida == (b"bytes", "image/jpeg")


@pytest.mark.asyncio
async def test_ler_imagem_sem_arquivo_no_storage_devolve_none(
    storage_local_isolado, monkeypatch
) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.services import diagnostico_provider

    imagens = [
        SimpleNamespace(
            url_arquivo="/api/v1/diagnosticos/imagens/sumiu.png", content_type="image/png"
        )
    ]
    monkeypatch.setattr(
        diagnostico_provider.diagnostico_queries, "listar_imagens", AsyncMock(return_value=imagens)
    )

    assert await diagnostico_provider._ler_imagem(AsyncMock(), SimpleNamespace(id=1)) is None
