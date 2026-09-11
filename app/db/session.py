"""Configuração de conexão com o banco de dados PostgreSQL via SQLAlchemy async."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url.get_secret_value(),
    echo=settings.debug,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Classe base para todos os modelos ORM do projeto."""


async def get_async_session() -> AsyncGenerator[AsyncSession]:
    """Dependency que fornece uma sessão de banco para cada request."""
    async with async_session() as session:
        yield session
