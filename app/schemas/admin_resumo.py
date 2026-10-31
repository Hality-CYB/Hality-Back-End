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


class AdminResumoResponse(BaseModel):
    periodo: PeriodoResumo
    diagnosticos: DiagnosticosResumo
    revisao: RevisaoResumo
    # fica null ate a regra clinica de com/sem halitose ser confirmada
    # (null quer dizer que ainda nao existe, nao que deu zero)
    halitose: dict[str, int] | None = None
