"""Perfil do próprio usuário (/users/me).

Substitui os GET/PATCH /me prontos do fastapi-users para agregar o bloco
profissional e travar o payload aos campos permitidos. As rotas /users/{id}
(superuser) continuam vindo do fastapi-users — ver app/api/v1/api.py.
"""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.api.deps import CurrentUser, DbSession
from app.auth.policies import CORRELATION_HEADER, definir_correlation_id
from app.schemas.consentimento import ConsentimentosResponse, DecisaoConsentimento
from app.schemas.user import PasswordUpdate, UserRead, UserUpdate
from app.services import consentimento_service, perfil_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead, name="users:current_user")
async def obter_perfil(user: CurrentUser, db: DbSession) -> UserRead:
    return await perfil_service.obter_perfil(db=db, user=user)


@router.patch("/me", response_model=UserRead, name="users:patch_current_user")
async def atualizar_perfil(dados: UserUpdate, user: CurrentUser, db: DbSession) -> UserRead:
    try:
        return await perfil_service.atualizar_perfil(db=db, user=user, dados=dados)

    except perfil_service.DadosProfissionaisNaoPermitidosError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="dados profissionais restritos a profissionais",
        ) from exc

    except perfil_service.DataNascimentoNaoPermitidaError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="data de nascimento restrita a pacientes",
        ) from exc


@router.patch("/me/senha", status_code=status.HTTP_204_NO_CONTENT, name="users:change_password")
async def atualizar_senha(dados: PasswordUpdate, user: CurrentUser, db: DbSession) -> None:
    try:
        await perfil_service.atualizar_senha(db=db, user=user, dados=dados)
    except perfil_service.SenhaAtualInvalidaError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="senha atual inválida",
        ) from exc


@router.get(
    "/me/consentimentos",
    response_model=ConsentimentosResponse,
    name="users:current_user_consents",
)
async def obter_consentimentos(user: CurrentUser, db: DbSession) -> ConsentimentosResponse:
    """Estado atual de cada finalidade de consentimento do próprio titular."""
    return await consentimento_service.obter_estado(db, user.id)


@router.post(
    "/me/consentimentos",
    response_model=ConsentimentosResponse,
    name="users:record_current_user_consent",
)
async def registrar_consentimento(
    decisao: DecisaoConsentimento,
    user: CurrentUser,
    db: DbSession,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=100)] = None,
) -> ConsentimentosResponse:
    """Registra aceite ou revogação do próprio titular, sem sobrescrever eventos anteriores."""
    try:
        return await consentimento_service.registrar_decisao_do_titular(
            db,
            titular=user,
            decisao=decisao,
            referencia_coleta=definir_correlation_id(request.headers.get(CORRELATION_HEADER)),
            operation_key=idempotency_key,
        )

    except consentimento_service.VersaoDesatualizadaError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"versão do termo desatualizada; versão vigente: {exc.versao_vigente}",
        ) from exc
