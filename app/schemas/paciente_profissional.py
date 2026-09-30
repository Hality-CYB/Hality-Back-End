import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class VinculoCreate(BaseModel):
    """Seleção, pelo profissional, de um paciente já cadastrado para vincular."""

    paciente_email: EmailStr


class VinculoDetail(BaseModel):
    id: int
    paciente_id: uuid.UUID
    paciente_nome: str
    paciente_email: str
    data_vinculo: datetime
    ativo: bool


class VinculoListResponse(BaseModel):
    itens: list[VinculoDetail]


class AdminVinculoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paciente_id: uuid.UUID
    profissional_id: uuid.UUID


class AdminVinculoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ativo: bool


class AdminVinculoDetail(BaseModel):
    id: int
    paciente_id: uuid.UUID
    paciente_nome: str
    profissional_id: uuid.UUID
    profissional_nome: str
    data_vinculo: datetime
    ativo: bool
    encerrado_em: datetime | None


class AdminVinculoListResponse(BaseModel):
    itens: list[AdminVinculoDetail]
    pagina: int
    limite: int
    total: int
    total_paginas: int
