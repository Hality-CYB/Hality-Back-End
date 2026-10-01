"""Perfil do próprio usuário (/users/me).

Substitui os GET/PATCH /me prontos do fastapi-users para agregar o bloco
profissional e travar o payload aos campos permitidos. As rotas /users/{id}
(superuser) continuam vindo do fastapi-users — ver app/api/v1/api.py.
"""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.user import UserRead, UserUpdate
from app.services import perfil_service

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
