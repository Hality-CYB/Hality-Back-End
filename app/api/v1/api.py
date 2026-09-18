from fastapi import APIRouter

from app.api.v1.endpoints import (
    anamnese,
    auth,
    diagnostico,
    health,
)
from app.auth.users import fastapi_users
from app.schemas.user import UserCreate, UserRead, UserUpdate

api_router = APIRouter()

# Rotas de saúde, anamnese e diagnóstico (existentes)
api_router.include_router(health.router)

api_router.include_router(anamnese.router)

api_router.include_router(diagnostico.router)

# Autenticação — login/refresh/logout customizados (access JWT curto +
# refresh opaco em banco, ver app/api/v1/endpoints/auth.py). Não usa o
# get_auth_router() pronto do fastapi-users porque ele só emite o token de
# uma única strategy.
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])

# Registro de novos usuários
api_router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)

# Gerenciamento do perfil do usuário (/users/me)
api_router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)
