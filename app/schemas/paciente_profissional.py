from datetime import datetime

from pydantic import BaseModel


class PacienteProfissionalCreate(BaseModel):
    """Vinculo opcional, indicado no cadastro do paciente."""

    paciente_id: int
    profissional_id: int


class PacienteProfissionalDetail(BaseModel):
    id: int
    paciente_id: int
    profissional_id: int
    data_vinculo: datetime