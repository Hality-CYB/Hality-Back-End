"""Rotas de atendimento em que o profissional age sobre um paciente vinculado (US-090)."""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentActorDep
from app.api.v1.endpoints.anamnese import AnamneseRepoDep
from app.schemas.anamnese import AnamneseCreate, AnamneseCreated
from app.services import anamnese_service, atendimento_service

router = APIRouter(prefix="/pacientes", tags=["atendimento profissional"])


@router.post(
    "/{paciente_id}/anamneses",
    response_model=AnamneseCreated,
    status_code=status.HTTP_201_CREATED,
)
async def criar_anamnese_para_paciente(
    paciente_id: uuid.UUID,
    payload: AnamneseCreate,
    ator: CurrentActorDep,
    repo: AnamneseRepoDep,
) -> AnamneseCreated:
    try:
        return await anamnese_service.criar_anamnese_para_paciente(repo, ator, paciente_id, payload)
    except atendimento_service.AtorNaoProfissionalError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="apenas profissionais podem atender outro paciente",
        ) from exc
    except atendimento_service.VinculoInexistenteError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="profissional sem vínculo com o paciente",
        ) from exc
    except atendimento_service.TitularIndisponivelError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="paciente indisponível"
        ) from exc
    except anamnese_service.AnamneseValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.erros) from exc
