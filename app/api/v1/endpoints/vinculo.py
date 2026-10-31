import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentProfessionalDep, DbSession
from app.schemas.paciente_profissional import VinculoCreate, VinculoDetail, VinculoListResponse
from app.services import vinculo_service

router = APIRouter(prefix="/vinculos", tags=["vinculos"])


@router.get("", response_model=VinculoListResponse)
async def listar_vinculos(
    profissional: CurrentProfessionalDep,
    db: DbSession,
) -> VinculoListResponse:
    return await vinculo_service.listar_vinculos(db=db, profissional_id=profissional.id)


@router.post("", response_model=VinculoDetail, status_code=status.HTTP_201_CREATED)
async def criar_vinculo(
    dados: VinculoCreate,
    profissional: CurrentProfessionalDep,
    db: DbSession,
) -> VinculoDetail:
    try:
        return await vinculo_service.criar_vinculo(
            db=db,
            profissional_id=profissional.id,
            paciente_email=dados.paciente_email,
        )

    except vinculo_service.PacienteNaoEncontradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="paciente não encontrado",
        ) from exc

    except vinculo_service.PacienteInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.motivo,
        ) from exc

    except vinculo_service.VinculoJaExisteError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="paciente já vinculado a este profissional",
        ) from exc


@router.delete("/{paciente_id}", status_code=status.HTTP_204_NO_CONTENT)
async def desvincular(
    paciente_id: uuid.UUID,
    profissional: CurrentProfessionalDep,
    db: DbSession,
) -> None:
    try:
        await vinculo_service.desvincular(
            db=db,
            profissional_id=profissional.id,
            paciente_id=paciente_id,
        )

    except vinculo_service.VinculoNaoEncontradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="vínculo não encontrado",
        ) from exc
