"""Fixtures compartilhadas pelos testes.

Os testes de anamnese exercitam a API completa (TestClient -> service ->
repositório real) contra o Postgres configurado em `.env`. O `paciente_id`
hoje vem de um stub fixo (`get_current_patient`, ver app/api/deps.py —
autenticação real é outra issue), então este fixture garante que esse id
exista em `users`, independente do que outros processos (como o seed) já
tenham inserido, e limpa as anamneses criadas durante o teste.

A fixture roda em um `asyncio.run()` próprio, num loop diferente do usado
pelo TestClient para as requisições. Por isso usa uma engine descartável
(NullPool, sem pooling) só para esse setup/teardown, em vez da engine
compartilhada de `app.db.session` — evitar que uma conexão criada aqui seja
reaproveitada depois por outro loop, o que causa `RuntimeError: Event loop
is closed`.
"""

import asyncio
from collections.abc import Iterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models import Anamnese, User

TEST_PATIENT_ID = 1


@pytest.fixture(autouse=True)
def _paciente_de_teste() -> Iterator[None]:
    asyncio.run(_preparar())
    yield
    asyncio.run(_limpar())


async def _preparar() -> None:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as db:
            usuario = await db.get(User, TEST_PATIENT_ID)
            if usuario is None:
                db.add(
                    User(
                        id=TEST_PATIENT_ID,
                        name="Paciente de Teste",
                        email="paciente.teste@hality.local",
                        hashed_password="x",
                        role="patient",
                    )
                )
                await db.commit()
    finally:
        await engine.dispose()


async def _limpar() -> None:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as db:
            await db.execute(delete(Anamnese).where(Anamnese.paciente_id == TEST_PATIENT_ID))
            await db.commit()
    finally:
        await engine.dispose()
