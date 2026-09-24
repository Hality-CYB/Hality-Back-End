import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.db import diagnostico_queries, home_queries
from app.schemas.conteudo import ConteudoCreate, ConteudoUpdate
from app.services import conteudo_service


def _conteudo(**alteracoes):
    agora = datetime.now(UTC)
    admin_id = uuid.uuid4()
    valores = {
        "id": 10,
        "titulo": "Higiene",
        "categoria": "higiene",
        "conteudo": {"itens": [{"tipo": "texto", "texto": "Use fio dental."}]},
        "classificacao_ids": [2],
        "aparece_na_home": False,
        "status": "rascunho",
        "ordem": 0,
        "created_at": agora,
        "updated_at": agora,
        "criado_por_id": admin_id,
        "atualizado_por_id": admin_id,
        "publicado_por_id": None,
        "publicado_em": None,
    }
    valores.update(alteracoes)
    return SimpleNamespace(**valores)


def test_novo_conteudo_nasce_rascunho() -> None:
    payload = ConteudoCreate.model_validate(
        {
            "titulo": "Higiene",
            "categoria": "higiene",
            "conteudo": {"itens": [{"tipo": "texto", "texto": "Use fio dental."}]},
        }
    )

    assert payload.status == "rascunho"


def test_conteudo_exige_ao_menos_um_bloco() -> None:
    with pytest.raises(ValidationError):
        ConteudoCreate.model_validate(
            {"titulo": "Inválido", "categoria": "higiene", "conteudo": {"itens": []}}
        )


def test_publicacao_registra_admin(monkeypatch) -> None:
    conteudo = _conteudo()
    admin_id = uuid.uuid4()

    async def buscar_por_id(db, conteudo_id):
        return conteudo

    async def atualizar(db, registro, valores):
        for campo, valor in valores.items():
            setattr(registro, campo, valor)
        return registro

    monkeypatch.setattr(conteudo_service.conteudo_queries, "buscar_por_id", buscar_por_id)
    monkeypatch.setattr(conteudo_service.conteudo_queries, "atualizar", atualizar)

    resultado = asyncio.run(
        conteudo_service.atualizar(
            SimpleNamespace(),
            admin_id=admin_id,
            conteudo_id=conteudo.id,
            payload=ConteudoUpdate(status="publicado"),
        )
    )

    assert resultado.status == "publicado"
    assert resultado.publicado_por_id == admin_id
    assert resultado.publicado_em is not None


def _sql_da_query(funcao, *args) -> str:
    class Resultado:
        def scalars(self):
            return self

        def all(self):
            return []

    class Db:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return Resultado()

    db = Db()
    asyncio.run(funcao(db, *args))
    return str(db.statement)


def test_queries_do_paciente_exigem_publicado_e_autoria() -> None:
    for sql in (
        _sql_da_query(diagnostico_queries.listar_conteudos_por_classificacao, 2),
        _sql_da_query(home_queries.listar_dicas_home),
    ):
        assert "conteudos.status" in sql
        assert "conteudos.criado_por_id IS NOT NULL" in sql
