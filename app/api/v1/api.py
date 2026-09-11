from fastapi import APIRouter

from app.api.v1.endpoints import anamnese, health
from app.core.users import fastapi_users, jwt_backend
from app.schemas.user import UserCreate, UserRead, UserUpdate

api_router = APIRouter()

# Rotas de saúde e anamnese (existentes)
api_router.include_router(health.router)
api_router.include_router(anamnese.router)

# Autenticação — login e logout gerenciados pelo fastapi-users
api_router.include_router(
    fastapi_users.get_auth_router(jwt_backend),
    prefix="/auth",
    tags=["auth"],
)

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
