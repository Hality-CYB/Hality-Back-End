"""Contratos públicos das ações de identidade."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.admin_usuario import SENHA_TAMANHO_MINIMO


class PasswordRecoveryRequest(BaseModel):
    email: EmailStr


class PasswordRecoveryConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=20)
    senha: str = Field(..., min_length=SENHA_TAMANHO_MINIMO)


class PasswordRecoveryResponse(BaseModel):
    message: str
