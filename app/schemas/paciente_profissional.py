import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


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
