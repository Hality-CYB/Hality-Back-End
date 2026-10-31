import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import profissional_queries
from app.schemas.profissionais import PeriodoResumo, ResumoProfissionalResponse


class PeriodoInvalidoError(Exception):
    pass


async def montar_resumo(
    db: AsyncSession,
    profissional_id: uuid.UUID,
    inicio: datetime,
    fim: datetime,
    timezone: str,
) -> ResumoProfissionalResponse:
    if inicio > fim:
        raise PeriodoInvalidoError

    pacientes_ids = await profissional_queries.listar_pacientes_ids(db, profissional_id)

    diagnosticos_total = await profissional_queries.contar_diagnosticos(
        db, pacientes_ids, inicio, fim
    )
    pendentes_revisao = await profissional_queries.contar_diagnosticos_pendentes(
        db, pacientes_ids, inicio, fim
    )
    ultimo_diagnostico_em = await profissional_queries.buscar_ultimo_diagnostico_em(
        db, pacientes_ids, inicio, fim
    )

    return ResumoProfissionalResponse(
        periodo=PeriodoResumo(inicio=inicio, fim=fim, timezone=timezone),
        pacientes_ativos=len(pacientes_ids),
        diagnosticos_total=diagnosticos_total,
        pendentes_revisao=pendentes_revisao,
        ultimo_diagnostico_em=ultimo_diagnostico_em,
    )
