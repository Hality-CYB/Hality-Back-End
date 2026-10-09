"""Administração dos vínculos paciente-profissional (US-110)."""

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
from app.schemas.paciente_profissional import (
    AdminVinculoCreate,
    AdminVinculoDetail,
    AdminVinculoListResponse,
    AdminVinculoUpdate,
)
from app.services import vinculo_service

router = APIRouter(
    prefix="/admin/vinculos",
    tags=["admin-vinculos"],
)


def _vinculo_nao_encontrado() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vínculo não encontrado")


def _vinculo_ja_existe() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail="já existe vínculo ativo para este par"
    )


def _entidade_invalida(motivo: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=motivo)


@router.get("", response_model=AdminVinculoListResponse)
async def listar_vinculos(
    admin: CurrentAdminDep,
    db: DbSession,
    pagina: PaginaQuery = 1,
    limite: LimiteQuery = 20,
    paciente_id: Annotated[uuid.UUID | None, Query()] = None,
    profissional_id: Annotated[uuid.UUID | None, Query()] = None,
    ativo: Annotated[bool | None, Query()] = None,
) -> AdminVinculoListResponse:
    return await vinculo_service.listar_vinculos_admin(
        db,
        pagina=pagina,
        limite=limite,
        paciente_id=paciente_id,
        profissional_id=profissional_id,
        ativo=ativo,
    )


@router.post("", response_model=AdminVinculoDetail, status_code=status.HTTP_201_CREATED)
async def criar_vinculo(
    dados: AdminVinculoCreate,
    admin: CurrentAdminMutationDep,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AdminVinculoDetail:
    try:
        return await vinculo_service.criar_vinculo_admin(
            db, dados.paciente_id, dados.profissional_id, admin, idempotency_key
        )

    except (
        vinculo_service.PacienteInvalidoError,
        vinculo_service.ProfissionalInvalidoError,
    ) as exc:
        raise _entidade_invalida(exc.motivo) from exc

    except vinculo_service.VinculoJaExisteError as exc:
        raise _vinculo_ja_existe() from exc


@router.patch("/{vinculo_id}", response_model=AdminVinculoDetail)
async def atualizar_vinculo(
    vinculo_id: int,
    dados: AdminVinculoUpdate,
    admin: CurrentAdminMutationDep,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AdminVinculoDetail:
    try:
        return await vinculo_service.atualizar_vinculo_admin(
            db, vinculo_id, dados.ativo, admin, idempotency_key
        )

    except vinculo_service.VinculoNaoEncontradoError as exc:
        raise _vinculo_nao_encontrado() from exc

    except (
        vinculo_service.PacienteInvalidoError,
        vinculo_service.ProfissionalInvalidoError,
    ) as exc:
        raise _entidade_invalida(exc.motivo) from exc

    except vinculo_service.VinculoJaExisteError as exc:
        raise _vinculo_ja_existe() from exc


@router.delete("/{vinculo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def encerrar_vinculo(
    vinculo_id: int,
    admin: CurrentAdminMutationDep,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> None:
    try:
        await vinculo_service.encerrar_vinculo_admin(db, vinculo_id, admin, idempotency_key)

    except vinculo_service.VinculoNaoEncontradoError as exc:
        raise _vinculo_nao_encontrado() from exc
