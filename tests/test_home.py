import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.services import home_service

PACIENTE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_OUTRO_PACIENTE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

HOME_URL = "/api/v1/home"


def _usuario(paciente_id=PACIENTE_ID):
    return SimpleNamespace(id=paciente_id, name="Mariana Oliveira", role="patient")


def _diagnostico(diagnostico_id=4, classificacao_id=None, status="concluido", data=None):
    return SimpleNamespace(
        id=diagnostico_id,
        status=status,
        data_diagnostico=data or datetime.now(UTC),
        classificacao_id=classificacao_id,
        escala_saburra=68 if classificacao_id else None,
    )


def _classificacao():
    return SimpleNamespace(codigo="NIVEL_3", nome_exibicao="Halitose Severa")


def _dica(dica_id, titulo="Beba água ao longo do dia", conteudo="Boa hidratação ajuda."):
    return SimpleNamespace(id=dica_id, titulo=titulo, conteudo=conteudo)


def _mockar_home_queries(
    monkeypatch,
    contar_diagnosticos=0,
    buscar_ultimo_diagnostico=None,
    contar_dicas=0,
    listar_dicas=(),
):
    monkeypatch.setattr(
        home_service.home_queries,
        "contar_diagnosticos",
        AsyncMock(return_value=contar_diagnosticos),
    )
    monkeypatch.setattr(
        home_service.home_queries,
        "buscar_ultimo_diagnostico",
        AsyncMock(return_value=buscar_ultimo_diagnostico),
    )
    monkeypatch.setattr(
        home_service.home_queries, "contar_dicas", AsyncMock(return_value=contar_dicas)
    )
    monkeypatch.setattr(
        home_service.home_queries, "listar_dicas", AsyncMock(return_value=list(listar_dicas))
    )


@pytest.mark.asyncio
async def test_home_sem_token_retorna_401(client: AsyncClient) -> None:
    response = await client.get(HOME_URL)

    assert response.status_code == 401


def test_home_sem_historico(monkeypatch):
    _mockar_home_queries(monkeypatch, contar_diagnosticos=0, contar_dicas=6)

    resultado = asyncio.run(home_service.montar_home(AsyncMock(), _usuario()))

    assert resultado.total_diagnosticos == 0
    assert resultado.ultimo_diagnostico is None
    assert resultado.avisos_nao_lidos == 0


def test_home_com_historico_usa_diagnostico_mais_recente(monkeypatch):
    diagnostico = _diagnostico(diagnostico_id=4, classificacao_id=3)

    _mockar_home_queries(
        monkeypatch, contar_diagnosticos=4, buscar_ultimo_diagnostico=diagnostico, contar_dicas=6
    )
    monkeypatch.setattr(
        home_service.diagnostico_queries,
        "buscar_classificacao",
        AsyncMock(return_value=_classificacao()),
    )

    resultado = asyncio.run(home_service.montar_home(AsyncMock(), _usuario()))

    assert resultado.total_diagnosticos == 4
    assert resultado.ultimo_diagnostico.id == 4
    assert resultado.ultimo_diagnostico.classificacao.codigo == "NIVEL_3"
    assert resultado.ultimo_diagnostico.classificacao.nome_exibicao == "Halitose Severa"


def test_home_diagnostico_sem_classificacao(monkeypatch):
    diagnostico = _diagnostico(diagnostico_id=5, classificacao_id=None, status="processando")

    _mockar_home_queries(
        monkeypatch, contar_diagnosticos=1, buscar_ultimo_diagnostico=diagnostico, contar_dicas=6
    )

    resultado = asyncio.run(home_service.montar_home(AsyncMock(), _usuario()))

    assert resultado.ultimo_diagnostico.classificacao is None


def test_home_total_dicas(monkeypatch):
    _mockar_home_queries(monkeypatch, contar_dicas=6)

    resultado = asyncio.run(home_service.montar_home(AsyncMock(), _usuario()))

    assert resultado.total_dicas == 6


def test_home_filtra_pelo_usuario_autenticado(monkeypatch):
    contar_diagnosticos = AsyncMock(return_value=0)
    buscar_ultimo_diagnostico = AsyncMock(return_value=None)

    monkeypatch.setattr(home_service.home_queries, "contar_diagnosticos", contar_diagnosticos)
    monkeypatch.setattr(
        home_service.home_queries, "buscar_ultimo_diagnostico", buscar_ultimo_diagnostico
    )
    monkeypatch.setattr(home_service.home_queries, "contar_dicas", AsyncMock(return_value=0))
    monkeypatch.setattr(home_service.home_queries, "listar_dicas", AsyncMock(return_value=[]))

    db = AsyncMock()
    asyncio.run(home_service.montar_home(db, _usuario(_OUTRO_PACIENTE_ID)))

    contar_diagnosticos.assert_awaited_once_with(db, _OUTRO_PACIENTE_ID)
    buscar_ultimo_diagnostico.assert_awaited_once_with(db, _OUTRO_PACIENTE_ID)


def test_home_avisos_nao_lidos_e_zero(monkeypatch):
    _mockar_home_queries(monkeypatch)

    resultado = asyncio.run(home_service.montar_home(AsyncMock(), _usuario()))

    assert resultado.avisos_nao_lidos == 0


def test_home_dicas_sem_registros_retorna_lista_vazia(monkeypatch):
    _mockar_home_queries(monkeypatch, contar_dicas=0, listar_dicas=[])

    resultado = asyncio.run(home_service.montar_home(AsyncMock(), _usuario()))

    assert resultado.dicas == []
    assert resultado.total_dicas == 0


def test_home_dicas_mapeadas_para_o_schema(monkeypatch):
    dicas = [
        _dica(1, titulo="O que é halitose?", conteudo="Texto sobre halitose."),
        _dica(2, titulo="Limpe a língua todos os dias", conteudo="Texto sobre saburra."),
    ]

    _mockar_home_queries(monkeypatch, contar_dicas=4, listar_dicas=dicas)

    resultado = asyncio.run(home_service.montar_home(AsyncMock(), _usuario()))

    assert [d.model_dump() for d in resultado.dicas] == [
        {"id": 1, "titulo": "O que é halitose?", "conteudo": "Texto sobre halitose."},
        {"id": 2, "titulo": "Limpe a língua todos os dias", "conteudo": "Texto sobre saburra."},
    ]
    assert resultado.total_dicas == 4


def test_home_pede_dicas_respeitando_o_limite_definido(monkeypatch):
    listar_dicas = AsyncMock(return_value=[])

    monkeypatch.setattr(home_service.home_queries, "contar_diagnosticos", AsyncMock(return_value=0))
    monkeypatch.setattr(
        home_service.home_queries, "buscar_ultimo_diagnostico", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(home_service.home_queries, "contar_dicas", AsyncMock(return_value=20))
    monkeypatch.setattr(home_service.home_queries, "listar_dicas", listar_dicas)

    db = AsyncMock()
    asyncio.run(home_service.montar_home(db, _usuario()))

    listar_dicas.assert_awaited_once_with(db, home_service.DICAS_HOME_LIMIT)
    assert home_service.DICAS_HOME_LIMIT == 3
