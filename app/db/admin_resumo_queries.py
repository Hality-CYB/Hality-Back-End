from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.diagnostico import Diagnostico

STATUS_CONCLUIDO = "concluido"


# as contas sao feitas no proprio banco (group by), sem trazer os diagnosticos pra memoria


async def contar_por_status(db: AsyncSession, inicio: datetime, fim: datetime) -> dict[str, int]:
    result = await db.execute(
        select(Diagnostico.status, func.count())
        .where(
            Diagnostico.data_diagnostico >= inicio,
            Diagnostico.data_diagnostico <= fim,
        )
        .group_by(Diagnostico.status)
    )

    return {status: total for status, total in result.all()}


async def contar_por_classificacao(
    db: AsyncSession, inicio: datetime, fim: datetime
) -> dict[int | None, int]:
    result = await db.execute(
        select(Diagnostico.classificacao_id, func.count())
        .where(
            Diagnostico.data_diagnostico >= inicio,
            Diagnostico.data_diagnostico <= fim,
        )
        .group_by(Diagnostico.classificacao_id)
    )

    return {classificacao_id: total for classificacao_id, total in result.all()}


async def contar_revisados(db: AsyncSession, inicio: datetime, fim: datetime) -> int:
    # revisado e o diagnostico concluido que um profissional ja revisou
    # (mesma regra que a tela de detalhe do diagnostico usa)
    result = await db.execute(
        select(func.count())
        .select_from(Diagnostico)
        .where(
            Diagnostico.data_diagnostico >= inicio,
            Diagnostico.data_diagnostico <= fim,
            Diagnostico.status == STATUS_CONCLUIDO,
            Diagnostico.profissional_revisor_id.is_not(None),
            Diagnostico.data_revisao.is_not(None),
        )
    )

    return result.scalar_one()
