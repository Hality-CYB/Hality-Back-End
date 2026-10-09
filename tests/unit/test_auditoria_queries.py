from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import auditoria_queries


class _SessaoComColisao:
    def __init__(self) -> None:
        self.adicionado = None
        self.rollback_count = 0

    async def scalar(self, statement):
        return None

    def add(self, registro) -> None:
        self.adicionado = registro

    async def flush(self) -> None:
        raise IntegrityError(
            "insert",
            {},
            Exception("uq_auditoria_acessos_chave_operacao chave_operacao"),
        )

    async def rollback(self) -> None:
        self.rollback_count += 1


def test_metadados_preservam_lista_de_campos() -> None:
    resultado = auditoria_queries._metadados_minimos(
        {"campos": ["name", "role"], "senha": "nao-gravar"}
    )

    assert resultado == {"campos": ["name", "role"]}


@pytest.mark.asyncio
async def test_colisao_de_chave_faz_rollback_e_vira_reutilizacao() -> None:
    session = _SessaoComColisao()

    with pytest.raises(auditoria_queries.ChaveOperacaoReutilizadaError):
        await auditoria_queries.registrar_mutacao(
            session,
            SimpleNamespace(id="ator", role="admin"),
            "conteudo.criar",
            "conteudo",
            1,
            operation_key="chave-1",
        )

    assert session.rollback_count == 1
