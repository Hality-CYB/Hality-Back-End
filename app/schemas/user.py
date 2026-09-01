"""Schemas Pydantic para autenticação e dados de usuário."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

# ─── Request schemas ────────────────────────────────────────────────────────────


class UserRegister(BaseModel):
    """Dados enviados no cadastro de um novo paciente."""

    name: str = Field(..., min_length=2, max_length=255, examples=["Maria Silva"])
    email: EmailStr = Field(..., examples=["maria@email.com"])
    phone: str | None = Field(None, max_length=20, examples=["(11) 99999-9999"])
    password: str = Field(..., min_length=6, max_length=128)


class UserLogin(BaseModel):
    """Dados enviados no login."""

    email: EmailStr
    password: str


# ─── Response schemas ───────────────────────────────────────────────────────────


class Token(BaseModel):
    """Token JWT retornado após login ou registro."""

    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """Dados públicos do usuário retornados pela API."""

    id: int
    name: str
    email: str
    phone: str | None = None
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
