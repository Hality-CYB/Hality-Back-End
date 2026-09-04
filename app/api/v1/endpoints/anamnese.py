from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentPatientDep
from app.db.anamnese_store import AnamneseRepositoryDep
from app.schemas.anamnese import AnamneseCreate, AnamneseCreated, AnamneseDetail, Questionario
from app.services import anamnese_service
from app.services.anamnese_questionnaire import get_questionario_ativo

router = APIRouter(prefix="/anamneses", tags=["anamnese"])


@router.get("/questionario", response_model=Questionario)
def obter_questionario() -> Questionario:
    return get_questionario_ativo()


@router.post("", response_model=AnamneseCreated, status_code=status.HTTP_201_CREATED)
def criar_anamnese(
    payload: AnamneseCreate,
    paciente_id: CurrentPatientDep,
    repo: AnamneseRepositoryDep,
) -> AnamneseCreated:
    # TODO(admin): no futuro, criação deve ser restrita a admin. Hoje qualquer
    # paciente autenticado cria a própria anamnese, como pede a issue #18—
    # a regra de acesso final fica pra quando papéis/admin existirem.
    try:
        return anamnese_service.criar_anamnese(repo, paciente_id, payload)
    except anamnese_service.AnamneseValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.erros) from exc


@router.get("", response_model=list[AnamneseDetail])
def listar_anamneses(
    paciente_id: CurrentPatientDep, repo: AnamneseRepositoryDep
) -> list[AnamneseDetail]:
    return anamnese_service.listar_anamneses(repo, paciente_id)


@router.get("/{anamnese_id}", response_model=AnamneseDetail)
def obter_anamnese(
    anamnese_id: int, paciente_id: CurrentPatientDep, repo: AnamneseRepositoryDep
) -> AnamneseDetail:
    try:
        return anamnese_service.obter_anamnese(repo, paciente_id, anamnese_id)
    except anamnese_service.AnamneseNaoEncontradaError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="anamnese não encontrada"
        ) from exc


@router.put("/{anamnese_id}", response_model=AnamneseDetail)
def atualizar_anamnese(
    anamnese_id: int,
    payload: AnamneseCreate,
    paciente_id: CurrentPatientDep,
    repo: AnamneseRepositoryDep,
) -> AnamneseDetail:
    # TODO(admin): no futuro, edição deve ser restrita a admin. Ainda não implementado.
    try:
        return anamnese_service.atualizar_anamnese(repo, paciente_id, anamnese_id, payload)
    except anamnese_service.AnamneseNaoEncontradaError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="anamnese não encontrada"
        ) from exc
    except anamnese_service.AnamneseValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.erros) from exc


@router.delete("/{anamnese_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_anamnese(
    anamnese_id: int, paciente_id: CurrentPatientDep, repo: AnamneseRepositoryDep
) -> None:
    # TODO(admin): no futuro, deleção deve ser restrita a admin. Ainda não implementado.
    try:
        anamnese_service.deletar_anamnese(repo, paciente_id, anamnese_id)
    except anamnese_service.AnamneseNaoEncontradaError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="anamnese não encontrada"
        ) from exc
