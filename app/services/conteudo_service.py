import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import auditoria_queries, conteudo_queries
from app.models.conteudo import Conteudo
from app.models.user import User
from app.schemas.conteudo import (
    CategoriaConteudo,
    ConteudoCreate,
    ConteudoDetail,
    ConteudoListResponse,
    ConteudoSchema,
    ConteudoUpdate,
    DestinoConteudo,
    OrdemConteudo,
    StatusConteudo,
    _validar_conteudo_publico,
    _validar_destinos_classificacoes,
)
from app.services import conteudo_storage

LIMITE_MAXIMO = 50
TAMANHO_MAXIMO_BUSCA = 100
ORDENS_LISTAGEM = set(OrdemConteudo)


class ConteudoNaoEncontradoError(Exception):
    pass


class ClassificacaoNaoEncontradaError(Exception):
    def __init__(self, ids: set[int]) -> None:
        self.ids = ids
        super().__init__(f"classificações não encontradas: {sorted(ids)}")


class ConteudoInvalidoError(Exception):
    pass


def _para_detalhe(conteudo: Conteudo) -> ConteudoDetail:
    return ConteudoDetail.model_validate(conteudo)


async def _validar_classificacoes(db: AsyncSession, ids: list[int]) -> None:
    ids_unicos = set(ids)
    existentes = await conteudo_queries.listar_classificacao_ids_existentes(
        db,
        list(ids_unicos),
    )
    ausentes = ids_unicos - existentes

    if ausentes:
        raise ClassificacaoNaoEncontradaError(ausentes)


def _registrar_publicacao(valores: dict, admin_id: uuid.UUID) -> None:
    valores["publicado_por_id"] = admin_id
    valores["publicado_em"] = datetime.now(UTC)


def _normalizar_destinos(
    destinos: list[DestinoConteudo] | list[str],
) -> list[str]:
    return [
        destino.value if isinstance(destino, DestinoConteudo) else destino for destino in destinos
    ]


def _sincronizar_home_legado(
    valores: dict,
    campos_informados: set[str],
    destinos_atuais: list[DestinoConteudo] | list[str] | None = None,
) -> None:
    destinos = _normalizar_destinos(valores.get("destinos", destinos_atuais or []))

    home = DestinoConteudo.HOME_AUTENTICADA.value

    # Compatibilidade com clientes antigos que ainda enviam
    # `aparece_na_home`.
    if "aparece_na_home" in campos_informados:
        if valores["aparece_na_home"]:
            if home not in destinos:
                destinos.append(home)
        else:
            destinos = [destino for destino in destinos if destino != home]

        valores["destinos"] = destinos
        return

    # Cliente novo enviou `destinos`: mantém o campo legado sincronizado
    # enquanto `aparece_na_home` ainda existir.
    if "destinos" in campos_informados:
        valores["aparece_na_home"] = home in destinos


def _validar_estado_conteudo(
    valores: dict,
    conteudo_atual: Conteudo | None = None,
) -> None:
    destinos = _normalizar_destinos(
        valores.get(
            "destinos",
            conteudo_atual.destinos if conteudo_atual is not None else [],
        )
    )

    classificacao_ids = valores.get(
        "classificacao_ids",
        conteudo_atual.classificacao_ids if conteudo_atual is not None else [],
    )

    conteudo = valores.get(
        "conteudo",
        conteudo_atual.conteudo if conteudo_atual is not None else None,
    )

    try:
        _validar_destinos_classificacoes(
            [DestinoConteudo(destino) for destino in destinos],
            classificacao_ids,
        )

        if DestinoConteudo.LANDING_PUBLICA.value in destinos:
            _validar_conteudo_publico(ConteudoSchema.model_validate(conteudo))
    except ValueError as exc:
        raise ConteudoInvalidoError(str(exc)) from exc


async def criar(
    db: AsyncSession,
    admin_id: uuid.UUID,
    payload: ConteudoCreate,
    actor: User | None = None,
    operation_key: str | None = None,
) -> ConteudoDetail:
    await _validar_classificacoes(db, payload.classificacao_ids)

    await auditoria_queries.validar_chave_operacao(
        db,
        actor=actor or admin_id,
        action="conteudo.criar",
        resource="conteudo",
        resource_id="novo",
        operation_key=operation_key,
    )

    valores = payload.model_dump(mode="json")

    _sincronizar_home_legado(
        valores,
        payload.model_fields_set,
    )

    _validar_estado_conteudo(valores)

    valores["criado_por_id"] = admin_id
    valores["atualizado_por_id"] = admin_id

    if payload.status == StatusConteudo.PUBLICADO:
        _registrar_publicacao(valores, admin_id)

    conteudo = await conteudo_queries.inserir(db, valores)

    if actor is not None:
        await auditoria_queries.registrar_mutacao(
            db,
            actor,
            "conteudo.criar",
            "conteudo",
            conteudo.id,
            operation_key=operation_key,
        )
        await db.commit()

    return _para_detalhe(conteudo)


async def listar(
    db: AsyncSession,
    *,
    page: int = 1,
    limit: int = 20,
    status: StatusConteudo | None = None,
    categoria: CategoriaConteudo | None = None,
    classificacao_id: int | None = None,
    aparece_na_home: bool | None = None,
    destino: DestinoConteudo | None = None,
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
        destino=destino,
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


async def obter(
    db: AsyncSession,
    conteudo_id: int,
) -> ConteudoDetail:
    conteudo = await conteudo_queries.buscar_por_id(db, conteudo_id)

    if conteudo is None:
        raise ConteudoNaoEncontradoError

    return _para_detalhe(conteudo)


async def atualizar(
    db: AsyncSession,
    admin_id: uuid.UUID,
    conteudo_id: int,
    payload: ConteudoUpdate,
    actor: User | None = None,
    operation_key: str | None = None,
) -> ConteudoDetail:
    conteudo = await conteudo_queries.buscar_por_id(db, conteudo_id)

    if conteudo is None:
        raise ConteudoNaoEncontradoError

    midias_antes = conteudo_storage.nomes_no_conteudo(conteudo.conteudo)

    alteracoes = payload.model_dump(
        mode="json",
        exclude_unset=True,
    )

    acao = "conteudo.publicar" if payload.status == StatusConteudo.PUBLICADO else "conteudo.editar"

    if payload.status == StatusConteudo.RASCUNHO and conteudo.status != StatusConteudo.RASCUNHO:
        acao = "conteudo.despublicar"

    await auditoria_queries.validar_chave_operacao(
        db,
        actor=actor or admin_id,
        action=acao,
        resource="conteudo",
        resource_id=conteudo.id,
        operation_key=operation_key,
    )

    _sincronizar_home_legado(
        alteracoes,
        payload.model_fields_set,
        conteudo.destinos,
    )

    if "classificacao_ids" in alteracoes:
        await _validar_classificacoes(
            db,
            alteracoes["classificacao_ids"],
        )

    _validar_estado_conteudo(
        alteracoes,
        conteudo,
    )

    status_anterior = conteudo.status

    alteracoes["atualizado_por_id"] = admin_id
    alteracoes["updated_at"] = datetime.now(UTC)

    if payload.status == StatusConteudo.PUBLICADO and conteudo.status != StatusConteudo.PUBLICADO:
        _registrar_publicacao(alteracoes, admin_id)

    elif payload.status == StatusConteudo.RASCUNHO:
        alteracoes["publicado_por_id"] = None
        alteracoes["publicado_em"] = None

    atualizado = await conteudo_queries.atualizar(
        db,
        conteudo,
        alteracoes,
    )

    if actor is not None:
        publicado = payload.status == StatusConteudo.PUBLICADO

        acao = "conteudo.publicar" if publicado else "conteudo.editar"

        if payload.status == StatusConteudo.RASCUNHO and status_anterior != StatusConteudo.RASCUNHO:
            acao = "conteudo.despublicar"

        await auditoria_queries.registrar_mutacao(
            db,
            actor,
            acao,
            "conteudo",
            conteudo.id,
            operation_key=operation_key,
        )
        await db.commit()

    await _remover_midias_orfas(
        db,
        midias_antes - conteudo_storage.nomes_no_conteudo(atualizado.conteudo),
    )

    return _para_detalhe(atualizado)


async def deletar(
    db: AsyncSession,
    conteudo_id: int,
    actor: User | None = None,
    operation_key: str | None = None,
) -> None:
    conteudo = await conteudo_queries.buscar_por_id(
        db,
        conteudo_id,
    )

    if conteudo is None:
        raise ConteudoNaoEncontradoError

    midias = conteudo_storage.nomes_no_conteudo(conteudo.conteudo)

    if actor is not None:
        await auditoria_queries.validar_chave_operacao(
            db,
            actor=actor,
            action="conteudo.remover",
            resource="conteudo",
            resource_id=conteudo.id,
            operation_key=operation_key,
        )

    await conteudo_queries.deletar(
        db,
        conteudo,
    )

    if actor is not None:
        await auditoria_queries.registrar_mutacao(
            db,
            actor,
            "conteudo.remover",
            "conteudo",
            conteudo.id,
            operation_key=operation_key,
        )
        await db.commit()

    await _remover_midias_orfas(db, midias)


async def _remover_midias_orfas(db: AsyncSession, nomes: set[str]) -> None:
    """Apaga os arquivos que saíram do conteúdo, se nenhum outro ainda os usa.

    Roda depois do commit: se a gravação falhar, nenhum arquivo é perdido.
    """
    for nome in nomes:
        if not await conteudo_queries.midia_em_uso(db, nome):
            await conteudo_storage.remover(nome)
