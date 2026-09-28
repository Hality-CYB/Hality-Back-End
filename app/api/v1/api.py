from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin_diagnosticos,
    anamnese,
    auth,
    diagnostico,
    health,
    home,
    users,
    vinculo,
)
from app.auth.users import fastapi_users
from app.schemas.user import UserAdminUpdate, UserCreate, UserRead

api_router = APIRouter()

# Rotas de saúde, anamnese e diagnóstico (existentes)
api_router.include_router(health.router)

api_router.include_router(anamnese.router)

api_router.include_router(diagnostico.router)

api_router.include_router(admin_diagnosticos.router)

api_router.include_router(home.router)

api_router.include_router(vinculo.router)

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

# Perfil do próprio usuário (GET/PATCH /users/me) — rotas próprias, com bloco
# profissional agregado e payload restrito aos campos permitidos.
api_router.include_router(users.router)

# Rotas /users/{id} (só superuser) do fastapi-users. As /me dele são removidas
# para não conflitarem com as de cima.
users_admin_router = fastapi_users.get_users_router(UserRead, UserAdminUpdate)
users_admin_router.routes = [
    rota for rota in users_admin_router.routes if getattr(rota, "path", None) != "/me"
]
api_router.include_router(users_admin_router, prefix="/users", tags=["users"])
