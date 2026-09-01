"""Testes unitários para o serviço de autenticação (app/services/auth_service.py)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.user import UserRegister
from app.services.auth_service import authenticate_user, get_user_by_email, register_patient


@pytest.mark.asyncio
async def test_register_patient_success(db_session: AsyncSession) -> None:
    """Valida cadastro bem-sucedido de um novo paciente."""
    user_in = UserRegister(
        name="Carlos Eduardo",
        email="carlos@hality.com",
        phone="(11) 98888-7777",
        password="SenhaSegura123",
    )

    user = await register_patient(db_session, user_in)

    assert user.id is not None
    assert user.name == "Carlos Eduardo"
    assert user.email == "carlos@hality.com"
    assert user.phone == "(11) 98888-7777"
    assert user.role == "patient"
    assert user.is_active is True
    assert user.hashed_password != "SenhaSegura123"


@pytest.mark.asyncio
async def test_register_patient_duplicate_email(db_session: AsyncSession) -> None:
    """Garante erro de ValueError ao tentar registrar e-mail já existente."""
    user_in = UserRegister(
        name="Ana Paula",
        email="ana@hality.com",
        phone="(11) 91111-2222",
        password="SenhaSegura123",
    )

    await register_patient(db_session, user_in)

    with pytest.raises(ValueError, match="E-mail já cadastrado."):
        await register_patient(db_session, user_in)


@pytest.mark.asyncio
async def test_authenticate_user_success(db_session: AsyncSession) -> None:
    """Valida autenticação com e-mail e senha corretos."""
    user_in = UserRegister(
        name="Fernanda Lima",
        email="fernanda@hality.com",
        password="SenhaCorreta123",
    )
    await register_patient(db_session, user_in)

    authenticated = await authenticate_user(db_session, "fernanda@hality.com", "SenhaCorreta123")
    assert authenticated is not None
    assert authenticated.email == "fernanda@hality.com"


@pytest.mark.asyncio
async def test_authenticate_user_wrong_password(db_session: AsyncSession) -> None:
    """Valida que senha incorreta retorna None."""
    user_in = UserRegister(
        name="Fernanda Lima",
        email="fernanda2@hality.com",
        password="SenhaCorreta123",
    )
    await register_patient(db_session, user_in)

    authenticated = await authenticate_user(db_session, "fernanda2@hality.com", "SenhaErrada")
    assert authenticated is None


@pytest.mark.asyncio
async def test_authenticate_user_nonexistent_email(db_session: AsyncSession) -> None:
    """Valida que e-mail não existente retorna None."""
    authenticated = await authenticate_user(db_session, "naoexiste@hality.com", "123456")
    assert authenticated is None


@pytest.mark.asyncio
async def test_get_user_by_email(db_session: AsyncSession) -> None:
    """Testa a busca de usuário por e-mail."""
    user_in = UserRegister(
        name="João Souza",
        email="joao@hality.com",
        password="SenhaSegura123",
    )
    await register_patient(db_session, user_in)

    found = await get_user_by_email(db_session, "joao@hality.com")
    assert found is not None
    assert found.name == "João Souza"

    not_found = await get_user_by_email(db_session, "inexistente@hality.com")
    assert not_found is None
