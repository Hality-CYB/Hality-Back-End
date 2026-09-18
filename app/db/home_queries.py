"""Consultas de dados para os componentes exibidos na Home."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conteudo import Conteudo
from app.models.diagnostico import Diagnostico


async def buscar_ultimo_diagnostico(db: AsyncSession, paciente_id: uuid.UUID) -> Diagnostico | None:
    resultado = await db.execute(
        select(Diagnostico)
        .where(Diagnostico.paciente_id == paciente_id)
        .order_by(Diagnostico.data_diagnostico.desc(), Diagnostico.id.desc())
        .limit(1)
    )
    return resultado.scalar_one_or_none()


async def listar_dicas_home(db: AsyncSession) -> list[Conteudo]:
    resultado = await db.execute(
        select(Conteudo)
        .where(Conteudo.aparece_na_home.is_(True))
        .order_by(Conteudo.ordem.asc(), Conteudo.id.asc())
    )
    return list(resultado.scalars().all())
