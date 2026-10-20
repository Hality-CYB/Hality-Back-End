"""Contratos públicos das ações de identidade."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.admin_usuario import SENHA_TAMANHO_MINIMO, SENHAS_PADRAO_PROIBIDAS
from app.schemas.consentimento import DecisaoConsentimento


class PasswordRecoveryRequest(BaseModel):
    email: EmailStr


class PasswordRecoveryConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=20)
    senha: str = Field(..., min_length=SENHA_TAMANHO_MINIMO)

    @field_validator("senha", mode="after")
    @classmethod
    def _validar_senha(cls, valor: str) -> str:
        if valor.strip().lower() in SENHAS_PADRAO_PROIBIDAS:
            raise ValueError("senha padrão não é permitida")
        return valor


class PasswordRecoveryResponse(BaseModel):
    message: str


class InvitationConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=20)
    senha: str = Field(..., min_length=SENHA_TAMANHO_MINIMO)
    consentimentos: list[DecisaoConsentimento] = Field(default_factory=list)

    @field_validator("senha", mode="after")
    @classmethod
    def _validar_senha(cls, valor: str) -> str:
        if valor.strip().lower() in SENHAS_PADRAO_PROIBIDAS:
            raise ValueError("senha padrão não é permitida")
        return valor
