"""Contratos públicos das ações de identidade."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.senha import SenhaNova
from app.schemas.consentimento import DecisaoConsentimento


class PasswordRecoveryRequest(BaseModel):
    email: EmailStr


class PasswordRecoveryConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=20)
    senha: SenhaNova


class PasswordRecoveryResponse(BaseModel):
    message: str


class InvitationConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=20)
    senha: SenhaNova
    consentimentos: list[DecisaoConsentimento] = Field(default_factory=list)
