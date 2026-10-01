import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentProfessional, DbSession
from app.schemas.paciente import PacienteDetail, PacienteListResponse
from app.services import paciente_service

# Só profissional, e só pacientes com vínculo ativo. Admin não herda acesso
# clínico (ver app/auth/policies.py); diagnósticos para o admin ficam em
# /admin/diagnosticos, com auditoria.
router = APIRouter(prefix="/pacientes", tags=["pacientes"])


@router.get("", response_model=PacienteListResponse)
async def listar_pacientes(
    usuario: CurrentProfessional,
    db: DbSession,
    busca: Annotated[str | None, Query()] = None,
    pagina: Annotated[int, Query()] = 1,
    limite: Annotated[int, Query()] = 20,
    ordem: Annotated[str, Query()] = "nome_asc",
) -> PacienteListResponse:
    try:
        return await paciente_service.listar_pacientes(
            db=db,
            usuario=usuario,
            busca=busca,
            pagina=pagina,
            limite=limite,
            ordem=ordem,
        )

    except paciente_service.PacienteFiltroInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.motivo,
        ) from exc


@router.get("/{paciente_id}", response_model=PacienteDetail)
async def obter_paciente(
    paciente_id: uuid.UUID,
    usuario: CurrentProfessional,
    db: DbSession,
    pagina: Annotated[int, Query()] = 1,
    limite: Annotated[int, Query()] = 20,
) -> PacienteDetail:
    try:
        return await paciente_service.obter_paciente(
            db=db,
            usuario=usuario,
            paciente_id=paciente_id,
            pagina=pagina,
            limite=limite,
        )

    except paciente_service.PacienteFiltroInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.motivo,
        ) from exc

    except paciente_service.PacienteNaoEncontradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="paciente não encontrado",
        ) from exc
