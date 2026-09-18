"""Fixtures compartilhadas pelos testes.

Hoje convivem DUAS estratégias de banco, uma por suíte:

* **Auth (`test_auth_api.py`) — SQLite em memória.** Usa `client`/`db_session`,
  que sobrescrevem `get_db`/`get_user_db`. Só a tabela `users` é criada (ver
  `TestBase` abaixo), então não precisa de container para rodar.

* **Anamnese (`test_anamnese.py`) — Postgres real do `.env`.** Exercita a API
  completa (TestClient -> service -> repositório) sem override nenhum, contra
  o banco migrado. Depende da fixture `_paciente_de_teste`.

A convivência é proposital e temporária: unificar as duas é trabalho de outra
branch. Por isso cada fixture declara seu escopo em vez de valer para todo
mundo — `_paciente_de_teste` não faz sentido para os testes de auth (que nem
falam com o Postgres), e criar tabelas no SQLite não faz sentido para os de
anamnese.

Os testes de anamnese também assumem que `get_questionario_ativo` está
usando o catálogo estático de fallback (anamnese_questionary.py), não uma
versão real cadastrada em `questionarios` (via scripts/seed.py, por exemplo)
- por isso a fixture tira um "snapshot" da tabela, esvazia ela pro teste
rodar determinístico, e restaura o snapshot no final. Isso evita que rodar
`pytest` depois do seed apague dado seedado, e evita que o seed quebre os
testes que têm payload fixo baseado no catálogo estático.

A fixture roda em um `asyncio.run()` próprio, num loop diferente do usado
pelo TestClient para as requisições. Por isso usa uma engine descartável
(NullPool, sem pooling) só para esse setup/teardown, em vez da engine
compartilhada de `app.db.session` — evitar que uma conexão criada aqui seja
reaproveitada depois por outro loop, o que causa `RuntimeError: Event loop
is closed`.
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Iterator
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException, Request, status
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.auth.users import current_active_user, get_refresh_token_db, get_user_db
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models import Anamnese, Questionario, RefreshToken, User

# Paciente fixo usado pela suíte de anamnese (Postgres real).
PACIENTE_STUB_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# ---------------------------------------------------------------------------
# Suíte de auth — SQLite em memória
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Base isolada para testes — registra apenas os modelos compatíveis com SQLite.
# Não usa o Base global (que inclui modelos com JSONB e outros tipos PostgreSQL-only).
class TestBase(DeclarativeBase):
    pass


if "users" not in TestBase.metadata.tables:
    User.__table__.to_metadata(TestBase.metadata)
if "refresh_tokens" not in TestBase.metadata.tables:
    RefreshToken.__table__.to_metadata(TestBase.metadata)


@pytest_asyncio.fixture
async def setup_db() -> AsyncGenerator[None]:
    """Cria as tabelas no banco SQLite em memória antes do teste e remove ao finalizar."""
    async with engine.begin() as conn:
        await conn.run_sync(TestBase.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(TestBase.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session(setup_db: None) -> AsyncGenerator[AsyncSession]:
    """Fixture que injeta uma sessão limpa do banco de testes."""
    async with TestingSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    """Fixture do AsyncClient da API configurado com o banco em memória."""

    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    async def override_get_user_db() -> AsyncGenerator[SQLAlchemyUserDatabase]:
        yield SQLAlchemyUserDatabase(db_session, User)

    async def override_get_refresh_token_db() -> AsyncGenerator[SQLAlchemyAccessTokenDatabase]:
        yield SQLAlchemyAccessTokenDatabase(db_session, RefreshToken)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_user_db] = override_get_user_db
    app.dependency_overrides[get_refresh_token_db] = override_get_refresh_token_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Suíte de anamnese — Postgres real
# ---------------------------------------------------------------------------

# O paciente_id vem de um stub fixo (`get_current_patient`, em app/api/deps.py).
# Este fixture garante que esse id exista em `users`, independente do que outros
# processos (como o seed) já tenham inserido, e limpa as anamneses do teste.
#
# Roda em um `asyncio.run()` próprio, num loop diferente do usado pelo TestClient
# para as requisições. Por isso usa uma engine descartável (NullPool, sem pooling)
# em vez da engine compartilhada de `app.db.session` — evita que uma conexão criada
# aqui seja reaproveitada depois por outro loop, o que causa
# `RuntimeError: Event loop is closed`.


async def _current_active_user_de_teste(request: Request) -> SimpleNamespace:
    """Override de `current_active_user` para a suíte de anamnese.

    Reproduz só a checagem de "token presente" do antigo stub (sem decodificar
    JWT de verdade) — o teste de auth "real" (login, token inválido, etc.)
    fica a cargo de `test_auth_api.py`, não desta suíte.
    """
    if not request.headers.get("authorization"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="sem token")
    return SimpleNamespace(id=PACIENTE_STUB_ID)


_MODULOS_COM_PACIENTE_DE_TESTE = {"test_anamnese", "test_diagnostico"}


@pytest.fixture(autouse=True)
def _paciente_de_teste(request: pytest.FixtureRequest) -> Iterator[None]:
    if request.module.__name__.rsplit(".", 1)[-1] not in _MODULOS_COM_PACIENTE_DE_TESTE:
        yield
        return

    app.dependency_overrides[current_active_user] = _current_active_user_de_teste
    questionarios_snapshot, anamneses_existentes = asyncio.run(_preparar())
    yield
    asyncio.run(_limpar(questionarios_snapshot, anamneses_existentes))
    del app.dependency_overrides[current_active_user]


async def _preparar() -> tuple[list[dict[str, Any]], set[int]]:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as db:
            usuario = await db.get(User, PACIENTE_STUB_ID)
            if usuario is None:
                db.add(
                    User(
                        id=PACIENTE_STUB_ID,
                        name="Paciente de Teste",
                        email="paciente.teste@hality.local",
                        hashed_password="x",
                        role="paciente",
                    )
                )
                await db.commit()

            anamneses_existentes = set(
                await db.scalars(
                    select(Anamnese.id).where(Anamnese.paciente_id == PACIENTE_STUB_ID)
                )
            )

            resultado = await db.execute(select(Questionario))
            snapshot = [
                {"versao": q.versao, "perguntas": q.perguntas, "criado_em": q.criado_em}
                for q in resultado.scalars().all()
            ]
            if snapshot:
                await db.execute(delete(Questionario))
                await db.commit()
            return snapshot, anamneses_existentes
    finally:
        await engine.dispose()


async def _limpar(
    questionarios_snapshot: list[dict[str, Any]], anamneses_existentes: set[int]
) -> None:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as db:
            await db.execute(
                delete(Anamnese).where(
                    Anamnese.paciente_id == PACIENTE_STUB_ID,
                    Anamnese.id.not_in(anamneses_existentes),
                )
            )
            if questionarios_snapshot:
                await db.execute(delete(Questionario))
                db.add_all(Questionario(**item) for item in questionarios_snapshot)
            await db.commit()
    finally:
        await engine.dispose()
