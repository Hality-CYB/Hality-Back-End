"""Contratos do CRUD administrativo de usuários e profissionais (US-110)."""

import uuid
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.schemas.usuario import TipoUsuario

SENHA_TAMANHO_MINIMO = 8


class _PayloadAdmin(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfissionalDados(_PayloadAdmin):
    registro_profissional: str | None = Field(None, max_length=50)
    especialidade: str | None = Field(None, max_length=100)
    vinculado_hality: bool = False


class AdminUsuarioCreate(_PayloadAdmin):
    nome: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    telefone: str | None = Field(None, max_length=20)
    role: TipoUsuario
    senha: str = Field(..., min_length=SENHA_TAMANHO_MINIMO)
    profissional: ProfissionalDados | None = None

    @model_validator(mode="after")
    def _profissional_so_para_role_profissional(self) -> Self:
        if self.profissional is not None and self.role != TipoUsuario.PROFISSIONAL:
            raise ValueError("dados de profissional só são aceitos com role profissional")
        return self


class AdminUsuarioUpdate(_PayloadAdmin):
    nome: str | None = Field(None, min_length=2, max_length=255)
    telefone: str | None = Field(None, max_length=20)
    ativo: bool | None = None
    role: TipoUsuario | None = None

    @field_validator("nome", "ativo", "role", mode="before")
    @classmethod
    def _nao_aceita_nulo(cls, valor: Any) -> Any:
        if valor is None:
            raise ValueError("não pode ser nulo")
        return valor


class AdminProfissionalUpdate(_PayloadAdmin):
    registro_profissional: str | None = Field(None, max_length=50)
    especialidade: str | None = Field(None, max_length=100)
    vinculado_hality: bool | None = None

    @field_validator("vinculado_hality", mode="before")
    @classmethod
    def _nao_aceita_nulo(cls, valor: Any) -> Any:
        if valor is None:
            raise ValueError("não pode ser nulo")
        return valor


class AdminProfissionalDetail(BaseModel):
    registro_profissional: str | None
    especialidade: str | None
    vinculado_hality: bool


class AdminUsuarioDetail(BaseModel):
    id: uuid.UUID
    nome: str
    email: str
    telefone: str | None
    role: str
    ativo: bool
    created_at: datetime
    profissional: AdminProfissionalDetail | None


class AdminUsuarioListResponse(BaseModel):
    itens: list[AdminUsuarioDetail]
    pagina: int
    limite: int
    total: int
    total_paginas: int
