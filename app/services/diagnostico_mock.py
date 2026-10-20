"""Fixture de desenvolvimento, não um modelo: resultado escolhido pelo ID e
confiança fixa. Grava `origem_resultado = 'mock'` sem provider nem versão."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.erros_diagnostico import CodigoErroDiagnostico
from app.db import diagnostico_queries
from app.models.diagnostico import Diagnostico
from app.schemas.diagnostico import OrigemResultado, StatusDiagnostico

MOCK_PROCESSING_SECONDS = 2.0


@dataclass(frozen=True)
class ResultadoMock:
    ordem_classificacao: int
    escala_saburra: int
    confianca_ia: float


_RESULTADOS = (
    ResultadoMock(
        ordem_classificacao=1,
        escala_saburra=24,
        confianca_ia=0.91,
    ),
    ResultadoMock(
        ordem_classificacao=2,
        escala_saburra=49,
        confianca_ia=0.89,
    ),
    ResultadoMock(
        ordem_classificacao=3,
        escala_saburra=68,
        confianca_ia=0.87,
    ),
)


def resultado_para(
    diagnostico_id: int,
) -> ResultadoMock:
    indice = (diagnostico_id - 1) % len(_RESULTADOS)

    return _RESULTADOS[indice]


def _processamento_concluido(
    diagnostico: Diagnostico,
) -> bool:
    criado_em = diagnostico.data_diagnostico

    if criado_em.tzinfo is None:
        criado_em = criado_em.replace(tzinfo=UTC)

    return (datetime.now(UTC) - criado_em).total_seconds() >= MOCK_PROCESSING_SECONDS


async def processar_se_necessario(
    db: AsyncSession,
    diagnostico: Diagnostico,
) -> Diagnostico:
    if diagnostico.status != StatusDiagnostico.PROCESSANDO or not _processamento_concluido(
        diagnostico
    ):
        return diagnostico

    resultado_mock = resultado_para(diagnostico.id)

    classificacao = await diagnostico_queries.buscar_classificacao_por_ordem(
        db,
        resultado_mock.ordem_classificacao,
    )

    if classificacao is None:
        return await diagnostico_queries.marcar_falha(
            db,
            diagnostico,
            origem=OrigemResultado.MOCK,
            erro_codigo=CodigoErroDiagnostico.CLASSIFICACAO_NAO_CONFIGURADA,
            erro_interno=(
                "classificação de ordem "
                f"{resultado_mock.ordem_classificacao} não cadastrada para o mock"
            ),
        )

    return await diagnostico_queries.concluir_mock(
        db,
        diagnostico,
        classificacao_id=classificacao.id,
        escala_saburra=resultado_mock.escala_saburra,
        confianca_ia=resultado_mock.confianca_ia,
    )
