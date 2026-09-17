"""Acesso a dados agregados para o resumo da Home — só SQL, nenhuma regra de negócio."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.diagnostico import Diagnostico
from app.models.dica import Dica


async def contar_diagnosticos(db: AsyncSession, paciente_id: uuid.UUID) -> int:
    resultado = await db.execute(
        select(func.count()).select_from(Diagnostico).where(Diagnostico.paciente_id == paciente_id)
    )
    return resultado.scalar_one()


async def buscar_ultimo_diagnostico(db: AsyncSession, paciente_id: uuid.UUID) -> Diagnostico | None:
    resultado = await db.execute(
        select(Diagnostico)
        .where(Diagnostico.paciente_id == paciente_id)
        .order_by(Diagnostico.data_diagnostico.desc())
        .limit(1)
    )
    return resultado.scalar_one_or_none()


async def contar_dicas(db: AsyncSession) -> int:
    resultado = await db.execute(select(func.count()).select_from(Dica))
    return resultado.scalar_one()


async def listar_dicas(db: AsyncSession, limite: int) -> list[Dica]:
    resultado = await db.execute(select(Dica).order_by(Dica.id.asc()).limit(limite))
    return list(resultado.scalars().all())
