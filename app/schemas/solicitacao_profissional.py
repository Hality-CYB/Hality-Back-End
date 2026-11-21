import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SolicitacaoProfissionalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nome: str = Field(min_length=2, max_length=255)
    email: EmailStr
    telefone: str | None = Field(default=None, max_length=20)
    registro_profissional: str = Field(min_length=2, max_length=50)
    especialidade: str = Field(min_length=2, max_length=100)
    aceita_termos: Literal[True]


class SolicitacaoProfissionalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nome: str
    email: str
    telefone: str | None
    registro_profissional: str
    especialidade: str
    status: Literal["pendente", "aprovada", "recusada"]
    created_at: datetime
    decidido_em: datetime | None
    usuario_id: uuid.UUID | None


class SolicitacoesProfissionaisRead(BaseModel):
    itens: list[SolicitacaoProfissionalRead]
    total: int
    pagina: int
    total_paginas: int


class DecisaoSolicitacao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisao: Literal["aprovada", "recusada"]
