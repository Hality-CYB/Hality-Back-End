"""UserManager — lógica de ciclo de vida do usuário (fastapi-users)."""

import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, UUIDIDMixin

from app.db.session import get_user_db
from app.models.user import User


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """Gerenciador de usuários com hooks de ciclo de vida.

    Estende o BaseUserManager do fastapi-users para:
    - Definir segredos para tokens de reset e verificação
    - Fornecer hooks que executam após eventos (registro, login, etc.)
    """

    reset_password_token_secret: str
    verification_token_secret: str

    def __init__(self, user_db, secret_key: str) -> None:
        super().__init__(user_db)
        self.reset_password_token_secret = secret_key
        self.verification_token_secret = secret_key

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        """Hook executado após o registro de um novo usuário."""
        print(f"Usuário {user.id} ({user.email}) registrado com sucesso.")

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        """Hook executado após solicitação de recuperação de senha."""
        print(f"Usuário {user.id} solicitou recuperação de senha. Token: {token}")

    async def on_after_request_verify(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        """Hook executado após solicitação de verificação de e-mail."""
        print(f"Verificação solicitada para {user.id}. Token: {token}")


async def get_user_manager(
    user_db=Depends(get_user_db),
) -> AsyncGenerator[UserManager]:
    """Dependency que fornece o UserManager configurado."""
    from app.core.config import get_settings

    settings = get_settings()
    yield UserManager(user_db, secret_key=settings.secret_key)
