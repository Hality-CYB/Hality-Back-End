from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentAdminDep, DbSession
from app.schemas.conteudo import ConteudoCreate, ConteudoDetail, ConteudoUpdate
from app.services import conteudo_service

router = APIRouter(prefix="/admin/conteudos", tags=["admin-conteudos"])


def _traduzir_erro(exc: Exception) -> HTTPException:
    if isinstance(exc, conteudo_service.ConteudoNaoEncontradoError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="conteúdo não encontrado"
        )
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("", response_model=ConteudoDetail, status_code=status.HTTP_201_CREATED)
async def criar_conteudo(
    payload: ConteudoCreate, admin_id: CurrentAdminDep, db: DbSession
) -> ConteudoDetail:
    try:
        return await conteudo_service.criar(db, admin_id, payload)
    except conteudo_service.ClassificacaoNaoEncontradaError as exc:
        raise _traduzir_erro(exc) from exc


@router.get("", response_model=list[ConteudoDetail])
async def listar_conteudos(admin_id: CurrentAdminDep, db: DbSession) -> list[ConteudoDetail]:
    return await conteudo_service.listar(db)


@router.get("/{conteudo_id}", response_model=ConteudoDetail)
async def obter_conteudo(
    conteudo_id: int, admin_id: CurrentAdminDep, db: DbSession
) -> ConteudoDetail:
    try:
        return await conteudo_service.obter(db, conteudo_id)
    except conteudo_service.ConteudoNaoEncontradoError as exc:
        raise _traduzir_erro(exc) from exc


@router.put("/{conteudo_id}", response_model=ConteudoDetail)
@router.patch("/{conteudo_id}", response_model=ConteudoDetail)
async def atualizar_conteudo(
    conteudo_id: int,
    payload: ConteudoUpdate,
    admin_id: CurrentAdminDep,
    db: DbSession,
) -> ConteudoDetail:
    try:
        return await conteudo_service.atualizar(db, admin_id, conteudo_id, payload)
    except (
        conteudo_service.ConteudoNaoEncontradoError,
        conteudo_service.ClassificacaoNaoEncontradaError,
    ) as exc:
        raise _traduzir_erro(exc) from exc


@router.delete("/{conteudo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deletar_conteudo(
    conteudo_id: int, admin_id: CurrentAdminDep, db: DbSession
) -> Response:
    try:
        await conteudo_service.deletar(db, conteudo_id)
    except conteudo_service.ConteudoNaoEncontradoError as exc:
        raise _traduzir_erro(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
