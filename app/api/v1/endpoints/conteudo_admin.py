from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Response, status

from app.api.deps import (
    CurrentAdminDep,
    CurrentAdminMutationDep,
    DbSession,
    LimiteQuery,
    PaginaQuery,
)
from app.schemas.conteudo import (
    CategoriaConteudo,
    ConteudoCreate,
    ConteudoDetail,
    ConteudoListResponse,
    ConteudoUpdate,
    OrdemConteudo,
    StatusConteudo,
)
from app.services import conteudo_service

router = APIRouter(prefix="/admin/conteudos", tags=["admin-conteudos"])


def _traduzir_erro(
    exc: conteudo_service.ConteudoNaoEncontradoError
    | conteudo_service.ClassificacaoNaoEncontradaError,
) -> HTTPException:
    if isinstance(exc, conteudo_service.ConteudoNaoEncontradoError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="conteúdo não encontrado"
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="uma ou mais classificações não foram encontradas",
    )


@router.post("", response_model=ConteudoDetail, status_code=status.HTTP_201_CREATED)
async def criar_conteudo(
    payload: ConteudoCreate,
    admin: CurrentAdminMutationDep,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ConteudoDetail:
    try:
        return await conteudo_service.criar(db, admin.id, payload, admin, idempotency_key)
    except conteudo_service.ClassificacaoNaoEncontradaError as exc:
        raise _traduzir_erro(exc) from exc


@router.get("", response_model=ConteudoListResponse)
async def listar_conteudos(
    admin: CurrentAdminDep,
    db: DbSession,
    page: PaginaQuery = 1,
    limit: LimiteQuery = 20,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status_filtro: Annotated[StatusConteudo | None, Query(alias="status")] = None,
    categoria: Annotated[CategoriaConteudo | None, Query()] = None,
    classificacao_id: Annotated[int | None, Query(ge=1)] = None,
    aparece_na_home: Annotated[bool | None, Query()] = None,
    order: Annotated[OrdemConteudo, Query()] = OrdemConteudo.ORDEM_ASC,
) -> ConteudoListResponse:
    try:
        return await conteudo_service.listar(
            db,
            page=page,
            limit=limit,
            q=q,
            status=status_filtro,
            categoria=categoria,
            classificacao_id=classificacao_id,
            aparece_na_home=aparece_na_home,
            order=order,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/{conteudo_id}", response_model=ConteudoDetail)
async def obter_conteudo(conteudo_id: int, admin: CurrentAdminDep, db: DbSession) -> ConteudoDetail:
    try:
        return await conteudo_service.obter(db, conteudo_id)
    except conteudo_service.ConteudoNaoEncontradoError as exc:
        raise _traduzir_erro(exc) from exc


@router.put("/{conteudo_id}", response_model=ConteudoDetail)
@router.patch("/{conteudo_id}", response_model=ConteudoDetail)
async def atualizar_conteudo(
    conteudo_id: int,
    payload: ConteudoUpdate,
    admin: CurrentAdminMutationDep,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ConteudoDetail:
    try:
        return await conteudo_service.atualizar(
            db, admin.id, conteudo_id, payload, admin, idempotency_key
        )
    except (
        conteudo_service.ConteudoNaoEncontradoError,
        conteudo_service.ClassificacaoNaoEncontradaError,
    ) as exc:
        raise _traduzir_erro(exc) from exc


@router.delete("/{conteudo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deletar_conteudo(
    conteudo_id: int,
    admin: CurrentAdminMutationDep,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Response:
    try:
        await conteudo_service.deletar(db, conteudo_id, admin, idempotency_key)
    except conteudo_service.ConteudoNaoEncontradoError as exc:
        raise _traduzir_erro(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
