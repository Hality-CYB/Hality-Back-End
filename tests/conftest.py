"""Fixtures do pytest para testes de integração e unitários do backend."""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.session import Base, get_async_session, get_user_db
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_db() -> AsyncGenerator[None]:
    """Cria as tabelas no banco SQLite em memória antes de cada teste e remove ao finalizar."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """Fixture que injeta uma sessão limpa do banco de testes."""
    async with TestingSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    """Fixture do AsyncClient da API configurado com o banco em memória."""
    from fastapi_users.db import SQLAlchemyUserDatabase

    from app.models.user import User

    async def override_get_async_session() -> AsyncGenerator[AsyncSession]:
        yield db_session

    async def override_get_user_db() -> AsyncGenerator[SQLAlchemyUserDatabase]:
        yield SQLAlchemyUserDatabase(db_session, User)

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_user_db] = override_get_user_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client
    app.dependency_overrides.clear()
