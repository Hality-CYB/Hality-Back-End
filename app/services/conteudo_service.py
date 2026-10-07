import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import conteudo_queries
from app.models.conteudo import Conteudo
from app.schemas.conteudo import (
    CategoriaConteudo,
    ConteudoCreate,
    ConteudoDetail,
    ConteudoListResponse,
    ConteudoUpdate,
    OrdemConteudo,
    StatusConteudo,
)

LIMITE_MAXIMO = 50
TAMANHO_MAXIMO_BUSCA = 100
ORDENS_LISTAGEM = set(OrdemConteudo)


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


async def listar(
    db: AsyncSession,
    *,
    page: int = 1,
    limit: int = 20,
    status: StatusConteudo | None = None,
    categoria: CategoriaConteudo | None = None,
    classificacao_id: int | None = None,
    aparece_na_home: bool | None = None,
    q: str | None = None,
    order: OrdemConteudo = OrdemConteudo.ORDEM_ASC,
) -> ConteudoListResponse:
    if page < 1:
        raise ValueError("page deve ser maior ou igual a 1")
    if limit < 1 or limit > LIMITE_MAXIMO:
        raise ValueError(f"limit deve estar entre 1 e {LIMITE_MAXIMO}")
    if order not in ORDENS_LISTAGEM:
        raise ValueError("order inválido")
    busca = q.strip() if q else None
    if busca and len(busca) > TAMANHO_MAXIMO_BUSCA:
        raise ValueError(f"q deve ter no máximo {TAMANHO_MAXIMO_BUSCA} caracteres")
    itens, total = await conteudo_queries.listar(
        db,
        busca=busca or None,
        status=status,
        categoria=categoria,
        classificacao_id=classificacao_id,
        aparece_na_home=aparece_na_home,
        page=page,
        limit=limit,
        order=order,
    )
    return ConteudoListResponse(
        items=[_para_detalhe(item) for item in itens],
        total=total,
        page=page,
        limit=limit,
        has_next=page * limit < total,
    )


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
