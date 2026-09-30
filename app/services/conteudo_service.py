import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import conteudo_queries
from app.models.conteudo import Conteudo
from app.schemas.conteudo import (
    ConteudoCreate,
    ConteudoDetail,
    ConteudoUpdate,
    StatusConteudo,
)


class ConteudoNaoEncontradoError(Exception):
    pass


class ClassificacaoNaoEncontradaError(Exception):
    def __init__(self, ids: set[int]) -> None:
        self.ids = ids
        super().__init__(f"classificações não encontradas: {sorted(ids)}")


def _para_detalhe(conteudo: Conteudo) -> ConteudoDetail:
    return ConteudoDetail.model_validate(conteudo)


async def _validar_classificacoes(db: AsyncSession, ids: list[int]) -> None:
    ids_unicos = set(ids)
    existentes = await conteudo_queries.listar_classificacao_ids_existentes(db, list(ids_unicos))
    ausentes = ids_unicos - existentes
    if ausentes:
        raise ClassificacaoNaoEncontradaError(ausentes)


def _registrar_publicacao(valores: dict, admin_id: uuid.UUID) -> None:
    valores["publicado_por_id"] = admin_id
    valores["publicado_em"] = datetime.now(UTC)


async def criar(db: AsyncSession, admin_id: uuid.UUID, payload: ConteudoCreate) -> ConteudoDetail:
    await _validar_classificacoes(db, payload.classificacao_ids)
    valores = payload.model_dump(mode="json")
    valores["criado_por_id"] = admin_id
    valores["atualizado_por_id"] = admin_id
    if payload.status == StatusConteudo.PUBLICADO:
        _registrar_publicacao(valores, admin_id)
    return _para_detalhe(await conteudo_queries.inserir(db, valores))


async def listar(db: AsyncSession) -> list[ConteudoDetail]:
    return [_para_detalhe(item) for item in await conteudo_queries.listar(db)]


async def obter(db: AsyncSession, conteudo_id: int) -> ConteudoDetail:
    conteudo = await conteudo_queries.buscar_por_id(db, conteudo_id)
    if conteudo is None:
        raise ConteudoNaoEncontradoError
    return _para_detalhe(conteudo)


async def atualizar(
    db: AsyncSession,
    admin_id: uuid.UUID,
    conteudo_id: int,
    payload: ConteudoUpdate,
) -> ConteudoDetail:
    conteudo = await conteudo_queries.buscar_por_id(db, conteudo_id)
    if conteudo is None:
        raise ConteudoNaoEncontradoError

    alteracoes = payload.model_dump(mode="json", exclude_unset=True)
    if "classificacao_ids" in alteracoes:
        await _validar_classificacoes(db, alteracoes["classificacao_ids"])

    alteracoes["atualizado_por_id"] = admin_id
    alteracoes["updated_at"] = datetime.now(UTC)
    if payload.status == StatusConteudo.PUBLICADO and conteudo.status != StatusConteudo.PUBLICADO:
        _registrar_publicacao(alteracoes, admin_id)
    elif payload.status == StatusConteudo.RASCUNHO:
        alteracoes["publicado_por_id"] = None
        alteracoes["publicado_em"] = None

    return _para_detalhe(await conteudo_queries.atualizar(db, conteudo, alteracoes))


async def deletar(db: AsyncSession, conteudo_id: int) -> None:
    conteudo = await conteudo_queries.buscar_por_id(db, conteudo_id)
    if conteudo is None:
        raise ConteudoNaoEncontradoError
    await conteudo_queries.deletar(db, conteudo)
