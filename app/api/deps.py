"""Dependências reutilizáveis via Depends (settings, sessão de banco, usuário autenticado)."""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.users import current_active_user
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.usuario import TipoUsuario

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db)]

# Alias para compatibilidade com código legado
DbDep = DbSession

LIMITE_MAXIMO_PAGINA = 50
PaginaQuery = Annotated[int, Query(ge=1)]
LimiteQuery = Annotated[int, Query(ge=1, le=LIMITE_MAXIMO_PAGINA)]

# Usuário autenticado e ativo injetado via JWT (fastapi-users)
CurrentUser = Annotated[User, Depends(current_active_user)]


def get_current_patient_id(user: CurrentUser) -> uuid.UUID:
    """Retorna o id do usuário autenticado como paciente_id.

    Substitui o antigo stub que aceitava qualquer bearer token e devolvia
    um paciente fixo — agora o id vem do JWT validado pelo fastapi-users.
    """
    return user.id


CurrentPatientDep = Annotated[uuid.UUID, Depends(get_current_patient_id)]


def require_admin(user: CurrentUser) -> User:
    """Exige usuário autenticado com `role == "admin"` ou `is_superuser`.

    401 (sem token/token inválido) vem do fastapi-users; aqui só tratamos o 403
    para quem está autenticado mas não é administrador.
    """
    if user.role != TipoUsuario.ADMIN and not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="acesso restrito a administradores",
        )
    return user


CurrentAdminDep = Annotated[User, Depends(require_admin)]


def get_current_professional(user: CurrentUser) -> User:
    """Garante que o usuário autenticado tem papel de profissional."""
    if user.role != "profissional":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="acesso restrito a profissionais",
        )

    return user


CurrentProfessionalDep = Annotated[User, Depends(get_current_professional)]
