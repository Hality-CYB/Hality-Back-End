"""Acesso a dados do vínculo paciente↔profissional — só SQL, nenhuma regra de negócio.

Consumido por app/services/atendimento_service.py, que decide se o vínculo
autoriza o profissional a atuar em nome do paciente.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paciente_profissional import PacienteProfissional
from app.models.user import User


async def existe_vinculo(
    db: AsyncSession,
    profissional_id: uuid.UUID,
    paciente_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(PacienteProfissional.id)
        .where(
            PacienteProfissional.profissional_id == profissional_id,
            PacienteProfissional.paciente_id == paciente_id,
        )
        .limit(1)
    )

    return result.scalar_one_or_none() is not None


async def usuario_ativo(
    db: AsyncSession,
    usuario_id: uuid.UUID,
) -> bool:
    result = await db.execute(select(User.is_active).where(User.id == usuario_id))

    return bool(result.scalar_one_or_none())
