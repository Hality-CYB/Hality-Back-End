"""Regras de negócio de autenticação — registro e login de usuários."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash, verify_password
from app.models.user import User
from app.schemas.user import UserRegister


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Busca um usuário pelo e-mail. Retorna None se não encontrado."""
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def register_patient(db: AsyncSession, user_in: UserRegister) -> User:
    """Registra um novo paciente no banco.

    Levanta ValueError se o e-mail já estiver cadastrado.
    """
    existing = await get_user_by_email(db, user_in.email)
    if existing:
        raise ValueError("E-mail já cadastrado.")

    user = User(
        name=user_in.name,
        email=user_in.email,
        phone=user_in.phone,
        hashed_password=get_password_hash(user_in.password),
        role="patient",
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    """Valida credenciais de login. Retorna o usuário ou None."""
    user = await get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        return None
    return user
