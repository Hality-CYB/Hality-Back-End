"""Schemas Pydantic para autenticação e dados de usuário (fastapi-users)."""

import uuid

from fastapi_users import schemas
from pydantic import Field


class UserRead(schemas.BaseUser[uuid.UUID]):
    """Dados públicos do usuário retornados pela API."""

    name: str
    phone: str | None = None
    role: str


class UserCreate(schemas.BaseUserCreate):
    """Dados enviados no cadastro de um novo paciente."""

    name: str = Field(..., min_length=2, max_length=255, examples=["Maria Silva"])
    phone: str | None = Field(None, max_length=20, examples=["(11) 99999-9999"])


class UserUpdate(schemas.BaseUserUpdate):
    """Dados permitidos para atualização do perfil do usuário."""

    name: str | None = Field(None, min_length=2, max_length=255)
    phone: str | None = Field(None, max_length=20)
