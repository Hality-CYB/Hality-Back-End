from pydantic import BaseModel

from app.schemas.profissionais import PeriodoResumo


class DiagnosticosResumo(BaseModel):
    total: int
    # a chave e o id da classificacao, diagnostico que ainda nao tem
    # classificacao (processando ou com falha) fica em "sem_classificacao"
    por_classificacao: dict[str, int]
    por_status: dict[str, int]


class RevisaoResumo(BaseModel):
    pendentes: int
    revisados: int


class CelulaConcordancia(BaseModel):
    # nível pela ordem da classificação: 1 normal, 2 íntima, 3 social
    ia: int
    revisao: int
    total: int


class ConcordanciaIA(BaseModel):
    """Quanto a classificação da IA bateu com a revisão humana (profissional ou Hality)."""

    # diagnósticos do período com classificação da IA e revisão
    comparados: int
    # os que a revisão manteve no mesmo nível da IA
    concordantes: int
    # concordantes / comparados; null quando nada foi revisado no período
    taxa: float | None
    # sempre as 9 combinações de nível, mesmo as zeradas
    matriz: list[CelulaConcordancia]


class AdminResumoResponse(BaseModel):
    periodo: PeriodoResumo
    diagnosticos: DiagnosticosResumo
    revisao: RevisaoResumo
    concordancia: ConcordanciaIA
    # fica null ate a regra clinica de com/sem halitose ser confirmada
    # (null quer dizer que ainda nao existe, nao que deu zero)
    halitose: dict[str, int] | None = None
