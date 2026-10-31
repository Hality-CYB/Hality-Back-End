import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import auditoria_queries


class _ErroIntegridade:
    def __init__(
        self, sqlstate: str, constraint_name: str | None, cause: BaseException | None = None
    ) -> None:
        self.sqlstate = sqlstate
        self.constraint_name = constraint_name
        self.__cause__ = cause


class _SessaoComColisao:
    def __init__(self, erro=None) -> None:
        self.adicionado = None
        self.rollback_count = 0
        self.erro = erro or _ErroIntegridade(
            "23505",
            None,
            _ErroIntegridade("23505", "uq_auditoria_acessos_chave_operacao"),
        )

    async def scalar(self, statement):
        return None

    def add(self, registro) -> None:
        self.adicionado = registro

    async def flush(self) -> None:
        raise IntegrityError(
            "INSERT INTO auditoria_acessos (chave_operacao) VALUES (...) ",
            {},
            self.erro,
        )

    async def rollback(self) -> None:
        self.rollback_count += 1


class _Corrida:
    def __init__(self) -> None:
        self.flush_count = 0
        self.flushes_prontos = asyncio.Event()
        self.vencedor_definido = False


class _SessaoConcorrente:
    def __init__(self, corrida: _Corrida) -> None:
        self.corrida = corrida
        self.rollback_count = 0

    async def scalar(self, statement):
        return None

    def add(self, registro) -> None:
        pass

    async def flush(self) -> None:
        self.corrida.flush_count += 1
        if self.corrida.flush_count == 2:
            self.corrida.flushes_prontos.set()
        await self.corrida.flushes_prontos.wait()
        if self.corrida.vencedor_definido:
            raise IntegrityError(
                "INSERT INTO auditoria_acessos (chave_operacao) VALUES (...) ",
                {},
                _ErroIntegridade("23505", "uq_auditoria_acessos_chave_operacao"),
            )
        self.corrida.vencedor_definido = True

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


@pytest.mark.asyncio
async def test_outra_constraint_no_mesmo_insert_nao_vira_chave_reutilizada() -> None:
    session = _SessaoComColisao(_ErroIntegridade("23505", "uq_users_email"))

    with pytest.raises(IntegrityError):
        await auditoria_queries.registrar_mutacao(
            session,
            SimpleNamespace(id="ator", role="admin"),
            "conteudo.criar",
            "conteudo",
            1,
            operation_key="chave-1",
        )

    assert session.rollback_count == 0


@pytest.mark.asyncio
async def test_requisicoes_concorrentes_com_mesma_chave_tem_uma_vencedora() -> None:
    corrida = _Corrida()
    sessoes = [_SessaoConcorrente(corrida), _SessaoConcorrente(corrida)]

    resultados = await asyncio.gather(
        *(
            auditoria_queries.registrar_mutacao(
                session,
                SimpleNamespace(id="ator", role="admin"),
                "conteudo.criar",
                "conteudo",
                1,
                operation_key="chave-concorrente",
            )
            for session in sessoes
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(resultado, Exception) for resultado in resultados) == 1
    assert (
        sum(
            isinstance(resultado, auditoria_queries.ChaveOperacaoReutilizadaError)
            for resultado in resultados
        )
        == 1
    )
    assert sum(session.rollback_count for session in sessoes) == 1
