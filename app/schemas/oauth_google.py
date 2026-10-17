"""Contratos do login com Google (US-012)."""

from pydantic import BaseModel, ConfigDict, Field

from app.core.consentimentos import Finalidade
from app.schemas.consentimento import DecisaoConsentimento


class TrocaGoogleRequest(BaseModel):
    """Código de troca de uso único recebido no redirecionamento do callback.

    `consentimentos` só é exigido quando o callback indicou `etapa=consentimento`
    (conta nova): o aceite do tratamento de dados de saúde é obrigatório.
    """

    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(..., min_length=1, max_length=2048)
    consentimentos: list[DecisaoConsentimento] = Field(
        default_factory=list, max_length=len(Finalidade)
    )
