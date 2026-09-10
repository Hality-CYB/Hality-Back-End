from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentPatientDep, DbSession
from app.schemas.anamnese import AnamneseCreate, AnamneseCreated, AnamneseDetail, Questionario
from app.services import anamnese_service
from app.services.anamnese_questionnaire import get_questionario_ativo

router = APIRouter(prefix="/anamneses", tags=["anamnese"])


@router.get("/questionario", response_model=Questionario)
def obter_questionario() -> Questionario:
    return get_questionario_ativo()


@router.post("", response_model=AnamneseCreated, status_code=status.HTTP_201_CREATED)
async def criar_anamnese(
    payload: AnamneseCreate,
    paciente_id: CurrentPatientDep,
    db: DbSession,
) -> AnamneseCreated:
    # TODO(admin): no futuro, criação deve ser restrita a admin. Hoje qualquer
    # paciente autenticado cria a própria anamnese, como pede a issue #18—
    # a regra de acesso final fica pra quando papéis/admin existirem.
    try:
        return await anamnese_service.criar_anamnese(db, paciente_id, payload)
    except anamnese_service.AnamneseValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.erros) from exc


@router.get("", response_model=list[AnamneseDetail])
async def listar_anamneses(paciente_id: CurrentPatientDep, db: DbSession) -> list[AnamneseDetail]:
    return await anamnese_service.listar_anamneses(db, paciente_id)


@router.get("/{anamnese_id}", response_model=AnamneseDetail)
async def obter_anamnese(
    anamnese_id: int, paciente_id: CurrentPatientDep, db: DbSession
) -> AnamneseDetail:
    try:
        return await anamnese_service.obter_anamnese(db, paciente_id, anamnese_id)
    except anamnese_service.AnamneseNaoEncontradaError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="anamnese não encontrada"
        ) from exc


@router.put("/{anamnese_id}", response_model=AnamneseDetail)
async def atualizar_anamnese(
    anamnese_id: int,
    payload: AnamneseCreate,
    paciente_id: CurrentPatientDep,
    db: DbSession,
) -> AnamneseDetail:
    # TODO(admin): no futuro, edição deve ser restrita a admin. Ainda não implementado.
    try:
        return await anamnese_service.atualizar_anamnese(db, paciente_id, anamnese_id, payload)
    except anamnese_service.AnamneseNaoEncontradaError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="anamnese não encontrada"
        ) from exc
    except anamnese_service.AnamneseValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.erros) from exc


@router.delete("/{anamnese_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deletar_anamnese(anamnese_id: int, paciente_id: CurrentPatientDep, db: DbSession) -> None:
    # TODO(admin): no futuro, deleção deve ser restrita a admin. Ainda não implementado.
    try:
        await anamnese_service.deletar_anamnese(db, paciente_id, anamnese_id)
    except anamnese_service.AnamneseNaoEncontradaError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="anamnese não encontrada"
        ) from exc
