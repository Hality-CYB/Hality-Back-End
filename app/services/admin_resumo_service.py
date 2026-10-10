from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import admin_resumo_queries
from app.schemas.admin_resumo import AdminResumoResponse, DiagnosticosResumo, RevisaoResumo
from app.schemas.profissionais import PeriodoResumo

# a task pede um limite maximo de periodo mas nao fala quanto,
# falei com o Thiago e ele falou que 366 dias pode ficar
LIMITE_PERIODO_DIAS = 366

STATUS_PENDENTE = "aguardando_revisao"


class PeriodoInvalidoError(Exception):
    pass


class PeriodoMuitoLongoError(Exception):
    pass


async def montar_resumo(
    db: AsyncSession,
    inicio: datetime,
    fim: datetime,
    timezone: str,
) -> AdminResumoResponse:
    if inicio > fim:
        raise PeriodoInvalidoError

    if fim - inicio > timedelta(days=LIMITE_PERIODO_DIAS):
        raise PeriodoMuitoLongoError

    # o banco guarda as datas em UTC, entao converte antes de consultar
    inicio_utc = inicio.astimezone(UTC)
    fim_utc = fim.astimezone(UTC)

    por_status = await admin_resumo_queries.contar_por_status(db, inicio_utc, fim_utc)
    contagem_classificacao = await admin_resumo_queries.contar_por_classificacao(
        db, inicio_utc, fim_utc
    )
    revisados = await admin_resumo_queries.contar_revisados(db, inicio_utc, fim_utc)

    # o id da classificacao vira texto porque chave de json e texto
    por_classificacao = {}
    for classificacao_id, total in contagem_classificacao.items():
        if classificacao_id is None:
            por_classificacao["sem_classificacao"] = total
        else:
            por_classificacao[str(classificacao_id)] = total

    return AdminResumoResponse(
        periodo=PeriodoResumo(inicio=inicio, fim=fim, timezone=timezone),
        diagnosticos=DiagnosticosResumo(
            total=sum(por_status.values()),
            por_classificacao=por_classificacao,
            por_status=por_status,
        ),
        revisao=RevisaoResumo(
            pendentes=por_status.get(STATUS_PENDENTE, 0),
            revisados=revisados,
        ),
    )
