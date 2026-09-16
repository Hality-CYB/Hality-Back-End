"""Fixtures compartilhadas pelos testes.

Os testes de anamnese exercitam a API completa (TestClient -> service ->
repositório real) contra o Postgres configurado em `.env`. O `paciente_id`
hoje vem de um stub fixo (`get_current_patient`, ver app/api/deps.py —
autenticação real é outra issue), então este fixture garante que esse id
exista em `users`, independente do que outros processos (como o seed) já
tenham inserido, e limpa as anamneses criadas durante o teste.

Os testes também assumem que `get_questionario_ativo` está usando o
catálogo estático de fallback (anamnese_questionary.py), não uma versão
real cadastrada em `questionarios` (via scripts/seed.py, por exemplo) - por
isso a fixture tira um "snapshot" da tabela, esvazia ela pro teste rodar
determinístico, e restaura o snapshot no final. Isso evita que rodar
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
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models import Anamnese, Questionario, User

TEST_PATIENT_ID = 1


@pytest.fixture(autouse=True)
def _paciente_de_teste() -> Iterator[None]:
    questionarios_snapshot = asyncio.run(_preparar())
    yield
    asyncio.run(_limpar(questionarios_snapshot))


async def _preparar() -> list[dict[str, Any]]:
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
                        role="paciente",
                    )
                )
                await db.commit()

            resultado = await db.execute(select(Questionario))
            snapshot = [
                {"versao": q.versao, "perguntas": q.perguntas, "criado_em": q.criado_em}
                for q in resultado.scalars().all()
            ]
            if snapshot:
                await db.execute(delete(Questionario))
                await db.commit()
            return snapshot
    finally:
        await engine.dispose()


async def _limpar(questionarios_snapshot: list[dict[str, Any]]) -> None:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as db:
            await db.execute(delete(Anamnese).where(Anamnese.paciente_id == TEST_PATIENT_ID))
            if questionarios_snapshot:
                await db.execute(delete(Questionario))
                db.add_all(Questionario(**item) for item in questionarios_snapshot)
            await db.commit()
    finally:
        await engine.dispose()
