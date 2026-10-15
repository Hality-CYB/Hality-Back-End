"""Contratos de consentimento por finalidade (US-020)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.consentimentos import Finalidade


class DecisaoConsentimento(BaseModel):
    """Decisão do titular para uma finalidade, na versão do termo que ele viu."""

    model_config = ConfigDict(extra="forbid")

    finalidade: Finalidade
    versao: str = Field(..., min_length=1, max_length=20)
    aceito: bool


class TermoRead(BaseModel):
    finalidade: Finalidade
    versao: str
    obrigatorio: bool
    titulo: str
    texto: str


class TermosResponse(BaseModel):
    itens: list[TermoRead]


class ConsentimentoEstado(BaseModel):
    """Estado atual de uma finalidade, derivado do evento mais recente.

    `vigente` só é verdadeiro quando o último evento é um aceite NA versão
    vigente do termo. `requer_decisao` é verdadeiro sem nenhum evento ou
    quando o último evento é de uma versão antiga.
    """

    finalidade: Finalidade
    obrigatorio: bool
    versao_vigente: str
    versao_decidida: str | None
    aceito: bool | None
    vigente: bool
    requer_decisao: bool
    decidido_em: datetime | None


class ConsentimentosResponse(BaseModel):
    consentimentos: list[ConsentimentoEstado]
    # Instante do evento recém-gravado (POST) ou do mais recente (GET).
    recorded_at: datetime | None
