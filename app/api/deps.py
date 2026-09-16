"""Dependências reutilizáveis via Depends (settings, sessão de banco, usuário autenticado)."""

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.users import current_active_user
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.user import User

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db)]

# Alias para compatibilidade com código legado
DbDep = DbSession

# Usuário autenticado e ativo injetado via JWT (fastapi-users)
CurrentUser = Annotated[User, Depends(current_active_user)]


def get_current_patient_id(user: CurrentUser) -> uuid.UUID:
    """Retorna o id do usuário autenticado como paciente_id.

    Substitui o antigo stub que aceitava qualquer bearer token e devolvia
    um paciente fixo — agora o id vem do JWT validado pelo fastapi-users.
    """
    return user.id


CurrentPatientDep = Annotated[uuid.UUID, Depends(get_current_patient_id)]
