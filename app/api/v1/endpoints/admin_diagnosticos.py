"""Consulta administrativa de diagnósticos (US-120 / DELTA-08).

Somente leitura. Não há (e não deve haver, até DEC-04/DEC-07) rota de
mutation de rótulo nem de exportação. O guard de admin fica no router para
valer automaticamente para qualquer rota adicionada aqui no futuro.
"""


import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentAdminDep, DbSession, require_admin
from app.schemas.admin_diagnostico import (
    AdminDiagnosticoDetalhe,
    AdminDiagnosticoListResponse,
)
from app.services import diagnostico_service

router = APIRouter(
    prefix="/admin/diagnosticos",
    tags=["admin-diagnosticos"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=AdminDiagnosticoListResponse)
async def listar_diagnosticos_admin(
    db: DbSession,
    paciente_id: Annotated[uuid.UUID | None, Query()] = None,
    classificacao: Annotated[str | None, Query(description="código da classificação")] = None,
    sem_classificacao: Annotated[bool, Query()] = False,
    status_diagnostico: Annotated[str | None, Query(alias="status")] = None,
    data_inicio: Annotated[str | None, Query()] = None,
    data_fim: Annotated[str | None, Query()] = None,
    pagina: Annotated[int, Query()] = 1,
    limite: Annotated[int, Query()] = 20,
    ordem: Annotated[str, Query()] = "data_desc",
) -> AdminDiagnosticoListResponse:
    try:
        return await diagnostico_service.listar_diagnosticos_admin(
            db=db,
            paciente_id=paciente_id,
            classificacao=classificacao,
            sem_classificacao=sem_classificacao,
            status=status_diagnostico,
            data_inicio=data_inicio,
            data_fim=data_fim,
            pagina=pagina,
            limite=limite,
            ordem=ordem,
        )

    except diagnostico_service.DiagnosticoFiltroInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.motivo,
        ) from exc


@router.get("/{diagnostico_id}", response_model=AdminDiagnosticoDetalhe)
async def obter_diagnostico_admin(
    diagnostico_id: int,
    admin: CurrentAdminDep,
    db: DbSession,
) -> AdminDiagnosticoDetalhe:
    try:
        return await diagnostico_service.obter_diagnostico_admin(
            db=db,
            admin_id=admin.id,
            diagnostico_id=diagnostico_id,
        )

    except diagnostico_service.DiagnosticoNaoEncontradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="diagnóstico não encontrado",
        ) from exc
