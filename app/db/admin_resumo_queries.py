from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.classificacao_diagnostico import ClassificacaoDiagnostico
from app.models.diagnostico import Diagnostico
from app.models.diagnostico_revisao import DiagnosticoRevisao

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


async def contar_ia_versus_revisao(
    db: AsyncSession, inicio: datetime, fim: datetime
) -> dict[tuple[int, int], int]:
    """Quantos diagnósticos do período caíram em cada par (nível da IA, nível da revisão).

    Usa a revisão mais recente de cada diagnóstico (a que vale para o paciente) e
    só conta quem tem classificação da IA e revisão com classificação. O par sai
    pela `ordem` (1-3) das classificações, contado no próprio banco.
    """
    ultima = (
        select(
            DiagnosticoRevisao.diagnostico_id.label("diagnostico_id"),
            func.max(DiagnosticoRevisao.versao).label("versao"),
        )
        .group_by(DiagnosticoRevisao.diagnostico_id)
        .subquery()
    )
    ia = aliased(ClassificacaoDiagnostico)
    revisada = aliased(ClassificacaoDiagnostico)
    result = await db.execute(
        select(ia.ordem, revisada.ordem, func.count())
        .select_from(Diagnostico)
        .join(ia, ia.id == Diagnostico.classificacao_id)
        .join(ultima, ultima.c.diagnostico_id == Diagnostico.id)
        .join(
            DiagnosticoRevisao,
            (DiagnosticoRevisao.diagnostico_id == ultima.c.diagnostico_id)
            & (DiagnosticoRevisao.versao == ultima.c.versao),
        )
        .join(revisada, revisada.id == DiagnosticoRevisao.classificacao_id)
        .where(
            Diagnostico.data_diagnostico >= inicio,
            Diagnostico.data_diagnostico <= fim,
        )
        .group_by(ia.ordem, revisada.ordem)
    )
    return {(nivel_ia, nivel_revisao): total for nivel_ia, nivel_revisao, total in result.all()}
