"""Schemas Pydantic para autenticação e dados de usuário."""

import uuid

from pydantic import BaseModel, EmailStr, Field


class UserRead(BaseModel):
    """Dados públicos do usuário retornados pela API."""

    id: uuid.UUID
    email: EmailStr
    name: str
    phone: str | None = None
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    """Dados enviados no cadastro de um novo usuário."""

    email: EmailStr
    password: str = Field(..., min_length=8, examples=["SenhaSegura123!"])
    name: str = Field(..., min_length=2, max_length=255, examples=["Maria Silva"])
    phone: str | None = Field(None, max_length=20, examples=["(11) 99999-9999"])


class UserUpdate(BaseModel):
    """Dados permitidos para atualização do perfil do usuário."""

    name: str | None = Field(None, min_length=2, max_length=255)
    phone: str | None = Field(None, max_length=20)


class LoginRequest(BaseModel):
    """Corpo da requisição de login."""

    email: EmailStr
    password: str


class Token(BaseModel):
    """Resposta do endpoint de login com o token JWT."""

    access_token: str
    token_type: str = "bearer"
