import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentProfessional, DbSession
from app.api.v1.endpoints.anamnese import AnamneseRepoDep
from app.schemas.anamnese import AnamneseCreate, AnamneseCreated
from app.schemas.paciente import PacienteCreate, PacienteDetail, PacienteListResponse
from app.schemas.paciente_profissional import VinculoDetail
from app.services import anamnese_service, paciente_service

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


@router.post("", response_model=VinculoDetail, status_code=status.HTTP_201_CREATED)
async def criar_paciente(
    dados: PacienteCreate,
    usuario: CurrentProfessional,
    db: DbSession,
) -> VinculoDetail:
    """Profissional cadastra um paciente novo, que já sai vinculado a ele."""
    try:
        return await paciente_service.criar_paciente(db=db, usuario=usuario, dados=dados)

    except paciente_service.EmailJaCadastradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="e-mail já cadastrado",
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


@router.post(
    "/{paciente_id}/anamneses",
    response_model=AnamneseCreated,
    status_code=status.HTTP_201_CREATED,
)
async def criar_anamnese_para_paciente(
    paciente_id: uuid.UUID,
    payload: AnamneseCreate,
    usuario: CurrentProfessional,
    repo: AnamneseRepoDep,
) -> AnamneseCreated:
    """Profissional preenche a anamnese de um paciente vinculado (US-090)."""
    try:
        return await anamnese_service.criar_anamnese_para_paciente(
            repo, usuario, paciente_id, payload
        )

    except anamnese_service.PacienteNaoEncontradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="paciente não encontrado",
        ) from exc

    except anamnese_service.AnamneseValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.erros) from exc
