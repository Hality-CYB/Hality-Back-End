import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.admin_usuario import SENHA_TAMANHO_MINIMO
from app.schemas.diagnostico import DiagnosticoListResponse

SENHA_PADRAO_PACIENTE = "hality1234"


class PacienteListItem(BaseModel):
    id: uuid.UUID
    nome: str
    email: str
    telefone: str | None
    ativo: bool
    total_diagnosticos: int
    ultimo_diagnostico_em: datetime | None
    ultimo_nivel: int | None


class PacienteListResponse(BaseModel):
    itens: list[PacienteListItem]
    pagina: int
    limite: int
    total: int
    total_paginas: int


class PacienteVinculo(BaseModel):
    id: int
    profissional_id: uuid.UUID
    profissional_nome: str
    data_vinculo: datetime
    ativo: bool
    encerrado_em: datetime | None


class PacienteDetail(PacienteListItem):
    vinculos: list[PacienteVinculo]
    diagnosticos: DiagnosticoListResponse


class PacienteCreate(BaseModel):
    """Cadastro de um paciente novo pelo profissional, já vinculado a ele.

    A ``senha`` é provisória: se o profissional não informar, vale
    ``SENHA_PADRAO_PACIENTE``. Papel e ativo não vêm do cliente — sempre
    ``paciente`` e ativo.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nome: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    telefone: str | None = Field(None, max_length=20)
    senha: str = Field(SENHA_PADRAO_PACIENTE, min_length=SENHA_TAMANHO_MINIMO)
