from fastapi import APIRouter

from app.api.v1.endpoints import health
from app.api.v1.endpoints.auth import auth_backend, fastapi_users
from app.schemas.user import UserCreate, UserRead, UserUpdate

api_router = APIRouter()
api_router.include_router(health.router)

# Routers de autenticação (login / logout)
api_router.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"],
)

# Router de registro
api_router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)

# Router de reset de senha
api_router.include_router(
    fastapi_users.get_reset_password_router(),
    prefix="/auth",
    tags=["auth"],
)

# Router de verificação de e-mail
api_router.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/auth",
    tags=["auth"],
)

# Router de usuários (/users/me, etc.)
api_router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)
