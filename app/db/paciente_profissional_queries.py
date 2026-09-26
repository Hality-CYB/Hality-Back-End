"""Acesso a dados do vínculo paciente ↔ profissional — só SQL, nenhuma regra de negócio."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paciente_profissional import PacienteProfissional


async def profissional_tem_acesso(
    db: AsyncSession,
    paciente_id: uuid.UUID,
    profissional_id: uuid.UUID,
) -> bool:
    """True se existe vínculo **ativo** entre o profissional e o paciente."""
    result = await db.execute(
        select(PacienteProfissional.id)
        .where(
            PacienteProfissional.paciente_id == paciente_id,
            PacienteProfissional.profissional_id == profissional_id,
            PacienteProfissional.ativo.is_(True),
        )
        .limit(1)
    )

    return result.scalar_one_or_none() is not None


async def paciente_tem_vinculo_ativo(
    db: AsyncSession,
    paciente_id: uuid.UUID,
) -> bool:
    """True se o paciente tem vínculo **ativo** com algum profissional."""
    result = await db.execute(
        select(PacienteProfissional.id)
        .where(
            PacienteProfissional.paciente_id == paciente_id,
            PacienteProfissional.ativo.is_(True),
        )
        .limit(1)
    )

    return result.scalar_one_or_none() is not None
