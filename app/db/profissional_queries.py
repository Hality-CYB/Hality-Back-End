import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.diagnostico import Diagnostico
from app.models.paciente_profissional import PacienteProfissional

STATUS_PENDENTE = "aguardando_revisao"


async def listar_pacientes_ids(db: AsyncSession, profissional_id: uuid.UUID) -> list[uuid.UUID]:
    result = await db.execute(
        select(PacienteProfissional.paciente_id).where(
            PacienteProfissional.profissional_id == profissional_id
        )
    )

    return list(result.scalars().all())


async def contar_diagnosticos(
    db: AsyncSession,
    pacientes_ids: list[uuid.UUID],
    inicio: datetime,
    fim: datetime,
) -> int:
    if not pacientes_ids:
        return 0

    result = await db.execute(
        select(func.count())
        .select_from(Diagnostico)
        .where(
            Diagnostico.paciente_id.in_(pacientes_ids),
            Diagnostico.data_diagnostico >= inicio,
            Diagnostico.data_diagnostico <= fim,
        )
    )

    return result.scalar_one()


async def contar_diagnosticos_pendentes(
    db: AsyncSession,
    pacientes_ids: list[uuid.UUID],
    inicio: datetime,
    fim: datetime,
) -> int:
    if not pacientes_ids:
        return 0

    result = await db.execute(
        select(func.count())
        .select_from(Diagnostico)
        .where(
            Diagnostico.paciente_id.in_(pacientes_ids),
            Diagnostico.status == STATUS_PENDENTE,
            Diagnostico.data_diagnostico >= inicio,
            Diagnostico.data_diagnostico <= fim,
        )
    )

    return result.scalar_one()


async def buscar_ultimo_diagnostico_em(
    db: AsyncSession,
    pacientes_ids: list[uuid.UUID],
    inicio: datetime,
    fim: datetime,
) -> datetime | None:
    if not pacientes_ids:
        return None

    result = await db.execute(
        select(func.max(Diagnostico.data_diagnostico)).where(
            Diagnostico.paciente_id.in_(pacientes_ids),
            Diagnostico.data_diagnostico >= inicio,
            Diagnostico.data_diagnostico <= fim,
        )
    )

    return result.scalar_one_or_none()
