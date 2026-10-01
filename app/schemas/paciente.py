import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.diagnostico import DiagnosticoListResponse


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
