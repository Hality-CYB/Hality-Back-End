import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.data_nascimento import DataNascimento
from app.schemas.admin_usuario import SENHA_TAMANHO_MINIMO, SENHAS_PADRAO_PROIBIDAS
from app.schemas.diagnostico import DiagnosticoListResponse
from app.schemas.usuario import TipoUsuario

SENHA_PADRAO_PACIENTE = "hality1234"


class PacienteListItem(BaseModel):
    id: uuid.UUID
    nome: str
    email: str
    telefone: str | None
    data_nascimento: date | None
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

    A ``senha`` é opcional no fluxo de convite. Senhas padrão (ex.: hality1234)
    são explicitamente rejeitadas.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nome: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    telefone: str | None = Field(None, max_length=20)
    data_nascimento: DataNascimento
    senha: str | None = Field(None, min_length=SENHA_TAMANHO_MINIMO)

    @field_validator("senha", mode="after")
    @classmethod
    def _validar_senha(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        if valor.strip().lower() in SENHAS_PADRAO_PROIBIDAS:
            raise ValueError("senha padrão não é permitida")
        return valor


class PacienteCreateResponse(BaseModel):
    id: int
    role: str = TipoUsuario.PACIENTE.value
    paciente_id: uuid.UUID
    paciente_nome: str
    paciente_email: str
    data_vinculo: datetime
    ativo: bool
    convite_pendente: bool = True
    vinculo_id: int | None = None
