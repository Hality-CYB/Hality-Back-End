import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.api import deps
from app.db import profissional_queries
from app.services import profissional_service

RESUMO_URL = "/api/v1/profissional/resumo"

PROFISSIONAL_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
INICIO = datetime(2026, 8, 1, tzinfo=UTC)
FIM = datetime(2026, 8, 31, tzinfo=UTC)


def _usuario(usuario_id=PROFISSIONAL_ID, role="profissional"):
    return SimpleNamespace(id=usuario_id, role=role)


# funcao so pra nao ficar repetindo os mesmos monkeypatch em cada teste
def _mockar_queries(monkeypatch, pacientes_ids=(), total=0, pendentes=0, ultimo=None):
    monkeypatch.setattr(
        profissional_service.profissional_queries,
        "listar_pacientes_ids",
        AsyncMock(return_value=list(pacientes_ids)),
    )
    monkeypatch.setattr(
        profissional_service.profissional_queries,
        "contar_diagnosticos",
        AsyncMock(return_value=total),
    )
    monkeypatch.setattr(
        profissional_service.profissional_queries,
        "contar_diagnosticos_pendentes",
        AsyncMock(return_value=pendentes),
    )
    monkeypatch.setattr(
        profissional_service.profissional_queries,
        "buscar_ultimo_diagnostico_em",
        AsyncMock(return_value=ultimo),
    )


# testes da funcao que monta o resumo


def test_montar_resumo_profissional_sem_pacientes(monkeypatch):
    # profissional sem nenhum paciente vinculado, entao tudo tem que voltar zerado
    _mockar_queries(monkeypatch, pacientes_ids=[])

    resultado = asyncio.run(
        profissional_service.montar_resumo(
            db=AsyncMock(),
            profissional_id=PROFISSIONAL_ID,
            inicio=INICIO,
            fim=FIM,
            timezone="UTC",
        )
    )

    assert resultado.pacientes_ativos == 0
    assert resultado.diagnosticos_total == 0
    assert resultado.pendentes_revisao == 0
    assert resultado.ultimo_diagnostico_em is None


def test_montar_resumo_periodo_invalido_nao_chama_queries(monkeypatch):
    # se a data de inicio vier depois da data de fim isso e invalido,
    # tem que dar erro e nem chegar a chamar o banco
    listar = AsyncMock(return_value=[])
    monkeypatch.setattr(profissional_service.profissional_queries, "listar_pacientes_ids", listar)

    with pytest.raises(profissional_service.PeriodoInvalidoError):
        asyncio.run(
            profissional_service.montar_resumo(
                db=AsyncMock(),
                profissional_id=PROFISSIONAL_ID,
                inicio=FIM,
                fim=INICIO,
                timezone="UTC",
            )
        )

    listar.assert_not_awaited()


def test_montar_resumo_contagens_batem_com_as_queries(monkeypatch):
    # aqui e o caso "normal", com pacientes e diagnosticos, so pra ver
    # se os numeros do resumo batem com o que as queries retornaram
    pacientes_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    ultimo = datetime(2026, 8, 20, 15, 30, tzinfo=UTC)
    _mockar_queries(monkeypatch, pacientes_ids=pacientes_ids, total=7, pendentes=2, ultimo=ultimo)

    resultado = asyncio.run(
        profissional_service.montar_resumo(
            db=AsyncMock(),
            profissional_id=PROFISSIONAL_ID,
            inicio=INICIO,
            fim=FIM,
            timezone="UTC",
        )
    )

    assert resultado.pacientes_ativos == 3
    assert resultado.diagnosticos_total == 7
    assert resultado.pendentes_revisao == 2
    assert resultado.ultimo_diagnostico_em == ultimo
    assert resultado.periodo.inicio == INICIO
    assert resultado.periodo.fim == FIM
    assert resultado.periodo.timezone == "UTC"


# testes das queries (o "se nao tem paciente, nem precisa ir no banco")


def test_contar_diagnosticos_sem_pacientes_nao_acessa_banco():
    db = AsyncMock()

    resultado = asyncio.run(profissional_queries.contar_diagnosticos(db, [], INICIO, FIM))

    assert resultado == 0
    db.execute.assert_not_awaited()


def test_buscar_ultimo_diagnostico_sem_pacientes_retorna_none():
    db = AsyncMock()

    resultado = asyncio.run(profissional_queries.buscar_ultimo_diagnostico_em(db, [], INICIO, FIM))

    assert resultado is None
    db.execute.assert_not_awaited()


# testes do deps.py, que e quem decide se pode acessar essa rota


def test_get_current_professional_bloqueia_quem_nao_e_profissional():
    # paciente tentando acessar rota de profissional tem que tomar 403
    with pytest.raises(HTTPException) as exc_info:
        deps.get_current_professional(_usuario(role="paciente"))

    assert exc_info.value.status_code == 403


def test_get_current_professional_permite_profissional():
    usuario = _usuario(role="profissional")

    assert deps.get_current_professional(usuario) == usuario


# teste do endpoint em si (sem estar logado tem que dar 401)


@pytest.mark.asyncio
async def test_resumo_sem_token_retorna_401(client: AsyncClient) -> None:
    response = await client.get(RESUMO_URL)

    assert response.status_code == 401
