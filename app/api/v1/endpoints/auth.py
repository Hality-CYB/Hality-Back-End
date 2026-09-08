"""Configuração central do FastAPIUsers e routers de autenticação."""

import uuid

from fastapi_users import FastAPIUsers

from app.core.security import auth_backend
from app.core.user_manager import get_user_manager
from app.models.user import User

fastapi_users = FastAPIUsers[User, uuid.UUID](
    get_user_manager,
    [auth_backend],
)

# Dependency para injetar o usuário autenticado ativo nas rotas protegidas
current_active_user = fastapi_users.current_user(active=True)
