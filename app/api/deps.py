from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_current_patient(authorization: Annotated[str | None, Header()] = None) -> int:
    """Stub temporário de autenticação.

    TODO(auth): a autenticação real (JWT, cadastro/login) é outra issue.
    Por enquanto essa dependency só garante o 401 quando não há token
    (exigido pela issue #18) e devolve um paciente_id fixo — trocar pela
    validação/decodificação de token de verdade quando a issue de auth
    estiver pronta.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="sem token")
    return 1


CurrentPatientDep = Annotated[int, Depends(get_current_patient)]
