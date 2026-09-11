from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


# Esta classe só será usada caso o dentista puxe o cliente para uma consulta!!!
class StatusDiagnostico(StrEnum):
    GERADO = "gerado"
    EM_REVISAO = "em_revisao"
    REVISADO = "revisado"


class DiagnosticoCreate(BaseModel):
    """Gerado automaticamente pela IA a partir das imagens já enviadas.

    [confirmar] sem anamnese_id por enquanto - a padronização das perguntas
    da anamnese ainda vai ser repensada.
    """

    paciente_id: int
    classificacao_id: int
    escala_saburra: int = Field(ge=0, le=6, description="Escala 0-6 usada pela clinica")
    confianca_ia: float


class DiagnosticoCreated(BaseModel):
    """Resultado vai direto ao paciente assim que gerado."""

    id: int
    paciente_id: int
    classificacao_id: int
    escala_saburra: int
    confianca_ia: float
    status: StatusDiagnostico
    data_diagnostico: datetime


class DiagnosticoRevisao(BaseModel):
    """Corpo usado pelo profissional para revisar/validar um diagnóstico.

    A revisão é apenas auditoria/validação clínica - NÃO alimenta retreino do modelo.
    """

    profissional_revisor_id: int
    observacoes_revisao: str | None = None
    status: StatusDiagnostico = StatusDiagnostico.REVISADO


class DiagnosticoInteresseConsulta(BaseModel):
    """Preenchido quando o paciente clica no CTA pós-diagnóstico (ex: "marque sua consulta")."""

    interesse_consulta: datetime


class DiagnosticoDetail(BaseModel):
    id: int
    paciente_id: int
    data_diagnostico: datetime
    classificacao_id: int
    escala_saburra: int
    confianca_ia: float
    status: StatusDiagnostico
    profissional_revisor_id: int | None = None
    data_revisao: datetime | None = None
    observacoes_revisao: str | None = None
    interesse_consulta: datetime | None = None
