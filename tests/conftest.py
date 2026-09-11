"""Fixtures do pytest para testes de integração e unitários do backend."""

from collections.abc import AsyncGenerator

import pytest_asyncio
from fastapi_users.db import SQLAlchemyUserDatabase
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.users import get_user_db
from app.db.session import get_db
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Base isolada para testes — registra apenas os modelos compatíveis com SQLite.
# Não usa o Base global (que inclui modelos com JSONB e outros tipos PostgreSQL-only).
class TestBase(DeclarativeBase):
    pass


# Importar User faz a tabela ser registrada na metadata global.
# Copiamos apenas ela para o TestBase.
from app.models.user import User as _User  # noqa: E402

if "users" not in TestBase.metadata.tables:
    _User.__table__.to_metadata(TestBase.metadata)


@pytest_asyncio.fixture(autouse=True)
async def setup_db() -> AsyncGenerator[None]:
    """Cria as tabelas no banco SQLite em memória antes de cada teste e remove ao finalizar."""
    async with engine.begin() as conn:
        await conn.run_sync(TestBase.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(TestBase.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """Fixture que injeta uma sessão limpa do banco de testes."""
    async with TestingSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    """Fixture do AsyncClient da API configurado com o banco em memória."""

    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    async def override_get_user_db() -> AsyncGenerator[SQLAlchemyUserDatabase]:
        yield SQLAlchemyUserDatabase(db_session, _User)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_user_db] = override_get_user_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client
    app.dependency_overrides.clear()
