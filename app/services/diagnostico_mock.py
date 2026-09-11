from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classificacao_diagnostico import (
    ClassificacaoDiagnostico,
)
from app.models.diagnostico import Diagnostico

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
    indice = (
        diagnostico_id - 1
    ) % len(_RESULTADOS)

    return _RESULTADOS[indice]


async def processar_se_necessario(
    db: AsyncSession,
    diagnostico: Diagnostico,
) -> Diagnostico:
    if diagnostico.status != "processando":
        return diagnostico

    criado_em = (
        diagnostico.data_diagnostico
    )

    if criado_em.tzinfo is None:
        criado_em = criado_em.replace(
            tzinfo=UTC
        )

    decorrido = (
        datetime.now(UTC) - criado_em
    ).total_seconds()

    if (
        decorrido
        < MOCK_PROCESSING_SECONDS
    ):
        return diagnostico

    resultado_mock = resultado_para(
        diagnostico.id
    )

    result = await db.execute(
        select(
            ClassificacaoDiagnostico
        ).where(
            ClassificacaoDiagnostico.ordem
            == resultado_mock.ordem_classificacao
        )
    )

    classificacao = (
        result.scalar_one_or_none()
    )

    if classificacao is None:
        diagnostico.status = "falha"
        diagnostico.classificacao_id = None
        diagnostico.escala_saburra = None
        diagnostico.confianca_ia = None

        if hasattr(
            diagnostico,
            "erro",
        ):
            diagnostico.erro = (
                "Classificação necessária "
                "para o mock não está configurada."
            )

        await db.commit()
        await db.refresh(
            diagnostico
        )

        return diagnostico

    diagnostico.classificacao_id = (
        classificacao.id
    )

    diagnostico.escala_saburra = (
        resultado_mock.escala_saburra
    )

    diagnostico.confianca_ia = (
        resultado_mock.confianca_ia
    )

    diagnostico.status = "concluido"

    if hasattr(
        diagnostico,
        "erro",
    ):
        diagnostico.erro = None

    await db.commit()
    await db.refresh(
        diagnostico
    )

    return diagnostico