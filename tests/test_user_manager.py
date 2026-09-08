"""Testes unitários para o UserManager (app/core/user_manager.py)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_users.db import SQLAlchemyUserDatabase
from app.core.user_manager import UserManager
from app.models.user import User


async def _get_manager(db_session: AsyncSession) -> UserManager:
    """Helper para criar um UserManager com a sessão de testes."""
    user_db = SQLAlchemyUserDatabase(db_session, User)
    return UserManager(user_db, secret_key="test-secret-key")


@pytest.mark.asyncio
async def test_create_user_via_manager(db_session: AsyncSession) -> None:
    """Valida que o UserManager pode criar um usuário com campos customizados."""
    from fastapi_users.schemas import BaseUserCreate

    from app.schemas.user import UserCreate

    manager = await _get_manager(db_session)

    user_create = UserCreate(
        email="carlos@hality.com",
        password="SenhaSegura123!",
        name="Carlos Eduardo",
        phone="(11) 98888-7777",
    )

    user = await manager.create(user_create)

    assert user.email == "carlos@hality.com"
    assert user.name == "Carlos Eduardo"
    assert user.phone == "(11) 98888-7777"
    assert user.is_active is True
    assert user.hashed_password != "SenhaSegura123!"


@pytest.mark.asyncio
async def test_get_user_by_email(db_session: AsyncSession) -> None:
    """Testa a busca de usuário por e-mail via UserManager."""
    from app.schemas.user import UserCreate

    manager = await _get_manager(db_session)

    user_create = UserCreate(
        email="joao@hality.com",
        password="SenhaSegura123!",
        name="João Souza",
    )
    await manager.create(user_create)

    found = await manager.get_by_email("joao@hality.com")
    assert found is not None
    assert found.name == "João Souza"


@pytest.mark.asyncio
async def test_authenticate_success(db_session: AsyncSession) -> None:
    """Valida autenticação com e-mail e senha corretos."""
    from fastapi_users import models
    from app.schemas.user import UserCreate

    manager = await _get_manager(db_session)

    user_create = UserCreate(
        email="fernanda@hality.com",
        password="SenhaCorreta123!",
        name="Fernanda Lima",
    )
    await manager.create(user_create)

    from fastapi_users.authentication.strategy import Strategy
    from unittest.mock import MagicMock

    # Use the manager's authenticate method
    credentials = MagicMock()
    credentials.username = "fernanda@hality.com"
    credentials.password = "SenhaCorreta123!"

    user = await manager.authenticate(credentials)
    assert user is not None
    assert user.email == "fernanda@hality.com"


@pytest.mark.asyncio
async def test_authenticate_wrong_password(db_session: AsyncSession) -> None:
    """Valida que senha incorreta retorna None."""
    from app.schemas.user import UserCreate
    from unittest.mock import MagicMock

    manager = await _get_manager(db_session)

    user_create = UserCreate(
        email="fernanda2@hality.com",
        password="SenhaCorreta123!",
        name="Fernanda Lima",
    )
    await manager.create(user_create)

    credentials = MagicMock()
    credentials.username = "fernanda2@hality.com"
    credentials.password = "SenhaErrada"

    user = await manager.authenticate(credentials)
    assert user is None


@pytest.mark.asyncio
async def test_authenticate_nonexistent_email(db_session: AsyncSession) -> None:
    """Valida que e-mail não existente retorna None."""
    from unittest.mock import MagicMock

    manager = await _get_manager(db_session)

    credentials = MagicMock()
    credentials.username = "naoexiste@hality.com"
    credentials.password = "123456"

    user = await manager.authenticate(credentials)
    assert user is None
