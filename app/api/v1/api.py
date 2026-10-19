from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin_diagnosticos,
    admin_resumo,
    admin_usuarios,
    admin_vinculos,
    anamnese,
    auth,
    auth_google,
    consentimentos,
    conteudo,
    conteudo_admin,
    conteudo_publico,
    diagnostico,
    health,
    home,
    paciente,
    profissional,
    users,
    vinculo,
)

api_router = APIRouter()

# Rotas de saúde, anamnese e diagnóstico (existentes)
api_router.include_router(health.router)
api_router.include_router(anamnese.router)
api_router.include_router(conteudo_admin.router)
api_router.include_router(conteudo.router)
api_router.include_router(conteudo_publico.router)
api_router.include_router(diagnostico.router)
api_router.include_router(admin_diagnosticos.router)
api_router.include_router(admin_resumo.router)
api_router.include_router(home.router)
api_router.include_router(profissional.router)
api_router.include_router(vinculo.router)
api_router.include_router(paciente.router)
api_router.include_router(admin_usuarios.router)
api_router.include_router(admin_vinculos.router)

# Autenticação — login/refresh/logout customizados (access JWT curto +
# refresh opaco em banco, ver app/api/v1/endpoints/auth.py). Não usa o
# get_auth_router() pronto do fastapi-users porque ele só emite o token de
# uma única strategy.
api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["auth"],
)

# Login com Google para paciente (authorize, callback e troca de código).
api_router.include_router(auth_google.router)

# Registro de novos usuários: POST /auth/register está em auth.py (rota própria,
# porque o cadastro e os consentimentos precisam sair na mesma transação).
api_router.include_router(consentimentos.router)

# Perfil do próprio usuário (GET/PATCH /users/me) — rotas próprias, com bloco
# profissional agregado e payload restrito aos campos permitidos. As rotas
# GET/PATCH/DELETE /users/{id} do fastapi-users não são registradas: a
# administração de usuários é feita em /admin/usuarios, e o DELETE delas
# apagaria o usuário fisicamente.
api_router.include_router(users.router)
