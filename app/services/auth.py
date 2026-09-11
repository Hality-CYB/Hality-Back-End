"""Serviço de autenticação: registro, busca e verificação de usuários."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash, verify_password
from app.models.user import User
from app.schemas.user import UserCreate


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Busca um usuário pelo e-mail.

    Args:
        session: Sessão assíncrona do banco de dados.
        email: E-mail a ser pesquisado.

    Returns:
        Instância de ``User`` ou ``None`` se não encontrado.
    """
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def authenticate_user(
    session: AsyncSession, email: str, password: str
) -> User | None:
    """Valida as credenciais de um usuário.

    Args:
        session: Sessão assíncrona do banco de dados.
        email: E-mail do usuário.
        password: Senha em texto plano enviada pelo cliente.

    Returns:
        Instância de ``User`` se as credenciais forem válidas, ou ``None``.
    """
    user = await get_user_by_email(session, email)
    if user is None:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def register_user(session: AsyncSession, data: UserCreate) -> User:
    """Cria um novo usuário no banco de dados.

    Args:
        session: Sessão assíncrona do banco de dados.
        data: Dados de cadastro validados pelo schema ``UserCreate``.

    Returns:
        Instância do ``User`` criado.

    Raises:
        ValueError: Se o e-mail já estiver cadastrado.
    """
    existing = await get_user_by_email(session, data.email)
    if existing is not None:
        raise ValueError("E-mail já cadastrado.")

    user = User(
        email=data.email,
        hashed_password=get_password_hash(data.password),
        name=data.name,
        phone=data.phone,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
