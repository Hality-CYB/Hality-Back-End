from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin_usuarios,
    admin_vinculos,
    anamnese,
    auth,
    diagnostico,
    health,
    home,
    vinculo,
)
from app.auth.users import fastapi_users
from app.schemas.user import UserCreate, UserRead, UserUpdate

api_router = APIRouter()

# Rotas de saúde, anamnese e diagnóstico (existentes)
api_router.include_router(health.router)

api_router.include_router(anamnese.router)

api_router.include_router(diagnostico.router)

api_router.include_router(home.router)

api_router.include_router(vinculo.router)

api_router.include_router(admin_usuarios.router)

api_router.include_router(admin_vinculos.router)

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

# Gerenciamento do perfil do usuário (/users/me). O router do fastapi-users
# também traz GET/PATCH/DELETE /users/{id}; eles são descartados porque a
# administração de usuários é feita em /admin/usuarios, e o DELETE deles
# apagaria o usuário fisicamente.
_ROTAS_PERFIL_PROPRIO = {"users:current_user", "users:patch_current_user"}

users_router = fastapi_users.get_users_router(UserRead, UserUpdate)
users_router.routes = [
    rota for rota in users_router.routes if getattr(rota, "name", None) in _ROTAS_PERFIL_PROPRIO
]
api_router.include_router(users_router, prefix="/users", tags=["users"])
