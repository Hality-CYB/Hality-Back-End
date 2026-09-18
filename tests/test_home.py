import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.dialects import postgresql

from app.db import home_queries
from app.services import home_service

PACIENTE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

HOME_URL = "/api/v1/home"


def _usuario(usuario_id=PACIENTE_ID, role="paciente"):
    return SimpleNamespace(id=usuario_id, name="Mariana Oliveira", role=role)


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


def _dica(dica_id, titulo, categoria="higiene"):
    return SimpleNamespace(
        id=dica_id,
        titulo=titulo,
        categoria=categoria,
        ordem=dica_id,
        aparece_na_home=True,
        conteudo={
            "itens": [
                {"tipo": "texto", "texto": f"Conteúdo de {titulo}."},
            ]
        },
    )


def _mockar_home_queries(monkeypatch, diagnostico=None, dicas=()):
    monkeypatch.setattr(
        home_service.home_queries,
        "buscar_ultimo_diagnostico",
        AsyncMock(return_value=diagnostico),
    )
    monkeypatch.setattr(
        home_service.home_queries,
        "listar_dicas_home",
        AsyncMock(return_value=list(dicas)),
    )


@pytest.mark.asyncio
async def test_home_sem_token_retorna_401(client: AsyncClient) -> None:
    response = await client.get(HOME_URL)

    assert response.status_code == 401


def test_home_sem_historico_retorna_preview_nulo_e_dicas(monkeypatch):
    dicas = [_dica(1, "Higiene da Língua")]
    _mockar_home_queries(monkeypatch, dicas=dicas)

    resultado = asyncio.run(home_service.montar_home(AsyncMock(), _usuario()))

    assert resultado.model_dump() == {
        "usuario": {
            "id": PACIENTE_ID,
            "nome": "Mariana Oliveira",
            "tipo_usuario": "paciente",
        },
        "ultimo_diagnostico": None,
        "dicas": [
            {
                "id": 1,
                "titulo": "Higiene da Língua",
                "categoria": "higiene",
                "conteudo": {
                    "itens": [
                        {"tipo": "texto", "texto": "Conteúdo de Higiene da Língua."},
                    ]
                },
            }
        ],
    }


def test_home_com_historico_monta_preview_do_ultimo_diagnostico(monkeypatch):
    diagnostico = _diagnostico(diagnostico_id=4, classificacao_id=3)
    _mockar_home_queries(
        monkeypatch,
        diagnostico=diagnostico,
        dicas=[_dica(1, "Higiene da Língua"), _dica(2, "Hidratação", "saude")],
    )
    monkeypatch.setattr(
        home_service.diagnostico_queries,
        "buscar_classificacao",
        AsyncMock(return_value=_classificacao()),
    )

    resultado = asyncio.run(home_service.montar_home(AsyncMock(), _usuario()))

    assert resultado.ultimo_diagnostico.id == 4
    assert resultado.ultimo_diagnostico.classificacao.codigo == "NIVEL_3"
    assert resultado.ultimo_diagnostico.classificacao.nome_exibicao == "Halitose Severa"
    assert [dica.titulo for dica in resultado.dicas] == ["Higiene da Língua", "Hidratação"]


def test_home_diagnostico_sem_resultado_nao_expoe_classificacao(monkeypatch):
    diagnostico = _diagnostico(diagnostico_id=5, classificacao_id=None, status="processando")
    _mockar_home_queries(monkeypatch, diagnostico=diagnostico)

    resultado = asyncio.run(home_service.montar_home(AsyncMock(), _usuario()))

    assert resultado.ultimo_diagnostico.classificacao is None
    assert resultado.ultimo_diagnostico.escala_saburra is None


def test_home_repassa_conteudos_na_ordem_do_catalogo(monkeypatch):
    dicas = [_dica(2, "Segundo"), _dica(1, "Primeiro")]
    listar_dicas = AsyncMock(return_value=dicas)
    monkeypatch.setattr(
        home_service.home_queries,
        "buscar_ultimo_diagnostico",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(home_service.home_queries, "listar_dicas_home", listar_dicas)
    db = AsyncMock()

    resultado = asyncio.run(home_service.montar_home(db, _usuario()))

    listar_dicas.assert_awaited_once_with(db)
    assert [dica.id for dica in resultado.dicas] == [2, 1]


@pytest.mark.asyncio
async def test_query_de_dicas_filtra_e_ordena_conteudos_da_home():
    dicas = [_dica(1, "Higiene da Língua")]
    resultado = SimpleNamespace()
    resultado.scalars = lambda: SimpleNamespace(all=lambda: dicas)
    db = AsyncMock()
    db.execute.return_value = resultado

    assert await home_queries.listar_dicas_home(db) == dicas

    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "conteudos.aparece_na_home IS true" in sql
    assert "ORDER BY conteudos.ordem ASC, conteudos.id ASC" in sql
