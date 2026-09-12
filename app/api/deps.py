"""Dependências reutilizáveis via Depends (settings, sessão de banco, usuário autenticado)."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.users import current_active_user
from app.db.session import get_db
from app.models.user import User

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db)]

# Alias para compatibilidade com código legado
DbDep = DbSession

# Usuário autenticado e ativo injetado via JWT (fastapi-users)
CurrentUser = Annotated[User, Depends(current_active_user)]


# ---------------------------------------------------------------------------
# Stub para endpoints de anamnese (a ser substituído quando auth for unificada)
# ---------------------------------------------------------------------------

import uuid  # noqa: E402

from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # noqa: E402

_bearer = HTTPBearer()

# Paciente fixo do stub. Era o id inteiro 1; virou UUID junto com users.id.
PACIENTE_STUB_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def get_current_patient(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> uuid.UUID:
    """Stub temporário: valida presença do token e retorna paciente_id fixo.

    TODO: substituir pela decodificação real do JWT quando a issue de auth
    para anamnese estiver implementada. O `CurrentUser` acima já faz isso
    de verdade — este stub sobrevive só até os endpoints de anamnese
    migrarem para ele.
    """
    _ = credentials  # garante que o token existe
    return PACIENTE_STUB_ID


CurrentPatientDep = Annotated[uuid.UUID, Depends(get_current_patient)]
