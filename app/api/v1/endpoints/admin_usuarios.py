"""CRUD administrativo de usuários e profissionais (US-110)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status

from app.api.deps import (
    CurrentAdminDep,
    CurrentAdminMutationDep,
    DbSession,
    LimiteQuery,
    PaginaQuery,
)
from app.schemas.admin_usuario import (
    AdminProfissionalUpdate,
    AdminUsuarioCreate,
    AdminUsuarioDetail,
    AdminUsuarioListResponse,
    AdminUsuarioUpdate,
)
from app.schemas.usuario import TipoUsuario
from app.services import admin_usuario_service as service

router = APIRouter(
    prefix="/admin",
    tags=["admin-usuarios"],
)


def _usuario_nao_encontrado() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="usuário não encontrado")


@router.get("/usuarios", response_model=AdminUsuarioListResponse)
async def listar_usuarios(
    admin: CurrentAdminDep,
    db: DbSession,
    pagina: PaginaQuery = 1,
    limite: LimiteQuery = 20,
    role: Annotated[TipoUsuario | None, Query()] = None,
    ativo: Annotated[bool | None, Query()] = None,
    busca: Annotated[str | None, Query(max_length=255)] = None,
) -> AdminUsuarioListResponse:
    return await service.listar_usuarios(
        db, pagina=pagina, limite=limite, role=role, ativo=ativo, busca=busca
    )


@router.get("/usuarios/{usuario_id}", response_model=AdminUsuarioDetail)
async def obter_usuario(
    usuario_id: uuid.UUID, admin: CurrentAdminDep, db: DbSession
) -> AdminUsuarioDetail:
    try:
        return await service.obter_usuario(db, usuario_id)

    except service.UsuarioNaoEncontradoError as exc:
        raise _usuario_nao_encontrado() from exc


@router.post("/usuarios", response_model=AdminUsuarioDetail, status_code=status.HTTP_201_CREATED)
async def criar_usuario(
    dados: AdminUsuarioCreate,
    admin: CurrentAdminMutationDep,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AdminUsuarioDetail:
    try:
        return await service.criar_usuario(db, dados, admin, idempotency_key)

    except service.EmailJaCadastradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="e-mail já cadastrado"
        ) from exc


@router.patch("/usuarios/{usuario_id}", response_model=AdminUsuarioDetail)
async def atualizar_usuario(
    usuario_id: uuid.UUID,
    dados: AdminUsuarioUpdate,
    admin: CurrentAdminMutationDep,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AdminUsuarioDetail:
    try:
        return await service.atualizar_usuario(db, usuario_id, dados, admin, idempotency_key)

    except service.UsuarioNaoEncontradoError as exc:
        raise _usuario_nao_encontrado() from exc

    except service.TrocaDeRoleBloqueadaError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.motivo) from exc

    except service.UltimoAdministradorError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="é necessário manter ao menos um administrador ativo",
        ) from exc


@router.patch("/profissionais/{usuario_id}", response_model=AdminUsuarioDetail)
async def atualizar_profissional(
    usuario_id: uuid.UUID,
    dados: AdminProfissionalUpdate,
    admin: CurrentAdminMutationDep,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AdminUsuarioDetail:
    try:
        return await service.atualizar_profissional(db, usuario_id, dados, admin, idempotency_key)

    except service.ProfissionalNaoEncontradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="profissional não encontrado"
        ) from exc
