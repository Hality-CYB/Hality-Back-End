from datetime import datetime

from pydantic import BaseModel


class ProfissionalCreate(BaseModel):
    """Extensão de UsuarioCreate, preenchida quando tipo_usuario = profissional."""

    registro_profissional: str | None = None  # [confirmar] CRO/CRM - obrigatorio?
    especialidade: str | None = None
    vinculado_hality: bool = False


class ProfissionalDetail(BaseModel):
    usuario_id: int
    registro_profissional: str | None = None
    especialidade: str | None = None
    vinculado_hality: bool


class PeriodoResumo(BaseModel):
    inicio: datetime
    fim: datetime
    timezone: str


class ResumoProfissionalResponse(BaseModel):
    # nomes dos campos ainda nao sao definitivos, segundo a issue #68
    # (depende de uma decisao chamada DEC-05 que a gente nao tem acesso)
    periodo: PeriodoResumo
    pacientes_ativos: int
    diagnosticos_total: int
    pendentes_revisao: int
    ultimo_diagnostico_em: datetime | None
