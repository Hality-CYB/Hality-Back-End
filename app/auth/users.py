"""Configuração central do fastapi-users: adaptador DB, UserManager, JWT e instância principal."""

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import AuthenticationBackend, CookieTransport, JWTStrategy
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.models.user import User

# ---------------------------------------------------------------------------
# Adaptador de banco SQLAlchemy
# ---------------------------------------------------------------------------


async def get_user_db(  # noqa: B008
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    """Fornece o adaptador SQLAlchemy para o fastapi-users."""
    yield SQLAlchemyUserDatabase(session, User)


# ---------------------------------------------------------------------------
# UserManager — lógica de negócio de usuários
# ---------------------------------------------------------------------------


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """Gerenciador de usuários com suporte a UUID.

    Attributes:
        reset_password_token_secret: Segredo para tokens de reset de senha.
        verification_token_secret: Segredo para tokens de verificação de e-mail.
    """

    @property
    def reset_password_token_secret(self) -> str:  # type: ignore[override]
        return get_settings().secret_key.get_secret_value()

    @property
    def verification_token_secret(self) -> str:  # type: ignore[override]
        return get_settings().secret_key.get_secret_value()

    async def on_after_register(self, user: User, request=None) -> None:  # type: ignore[override]
        """Callback chamado após registro bem-sucedido (ex.: envio de e-mail de boas-vindas)."""


async def get_user_manager(  # noqa: B008
    user_db: Annotated[SQLAlchemyUserDatabase, Depends(get_user_db)],
) -> AsyncGenerator[UserManager, None]:
    """Dependency que fornece o UserManager para cada request."""
    yield UserManager(user_db)


# ---------------------------------------------------------------------------
# Transporte Cookie e estratégia JWT
# ---------------------------------------------------------------------------


def _get_cookie_transport() -> CookieTransport:
    """Cria o CookieTransport com TTL sincronizado com o Settings."""
    settings = get_settings()
    return CookieTransport(
        cookie_name="fastapiusersauth",
        cookie_max_age=settings.access_token_expire_minutes * 60,
        cookie_httponly=True,
        cookie_samesite="lax",
        cookie_secure=settings.environment == "production",
    )


cookie_transport = _get_cookie_transport()


def get_jwt_strategy() -> JWTStrategy:
    """Cria a estratégia JWT usando a chave secreta e tempo de expiração do Settings."""
    settings = get_settings()
    return JWTStrategy(
        secret=settings.secret_key.get_secret_value(),
        lifetime_seconds=settings.access_token_expire_minutes * 60,
    )


jwt_backend = AuthenticationBackend(
    name="jwt",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)

# ---------------------------------------------------------------------------
# Instância principal do FastAPIUsers
# ---------------------------------------------------------------------------

fastapi_users = FastAPIUsers[User, uuid.UUID](
    get_user_manager,
    [jwt_backend],
)

# Dependency pronta: retorna o usuário autenticado e ativo
current_active_user = fastapi_users.current_user(active=True)