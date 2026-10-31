"""Testes da lista de classificações (GET /classificacoes).

Rodam em SQLite em memoria, igual o test_admin_resumo.py.
"""

import uuid
from collections.abc import AsyncGenerator
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.users import current_active_user
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import ClassificacaoDiagnostico

pytestmark = pytest.mark.asyncio

URL = "/api/v1/classificacoes"


@pytest_asyncio.fixture
async def http() -> AsyncGenerator[AsyncClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=[ClassificacaoDiagnostico.__table__])
        )

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # inseridas fora de ordem, pra conferir que a resposta vem pelo nivel
    async with factory() as db:
        db.add_all(
            [
                ClassificacaoDiagnostico(
                    codigo="mau_halito_social", nome_exibicao="Mau Hálito Social", ordem=3
                ),
                ClassificacaoDiagnostico(
                    codigo="halito_normal", nome_exibicao="Hálito Normal", ordem=1
                ),
                ClassificacaoDiagnostico(
                    codigo="halitose_intima", nome_exibicao="Halitose Íntima", ordem=2
                ),
            ]
        )
        await db.commit()

    async def _override_get_db() -> AsyncGenerator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
    await engine.dispose()


def _como(role: str) -> None:
    app.dependency_overrides[current_active_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), role=role, is_active=True
    )


async def test_sem_token_retorna_401(http) -> None:
    assert (await http.get(URL)).status_code == 401


@pytest.mark.parametrize("role", ["paciente", "profissional", "admin"])
async def test_lista_as_classificacoes_em_ordem_de_nivel(http, role) -> None:
    _como(role)

    response = await http.get(URL)

    assert response.status_code == 200
    corpo = response.json()
    assert [c["codigo"] for c in corpo] == [
        "halito_normal",
        "halitose_intima",
        "mau_halito_social",
    ]
    assert [c["ordem"] for c in corpo] == [1, 2, 3]
    assert set(corpo[0]) == {"id", "codigo", "nome_exibicao", "ordem"}
    assert corpo[0]["nome_exibicao"] == "Hálito Normal"
