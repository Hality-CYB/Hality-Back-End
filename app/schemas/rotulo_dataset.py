from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.diagnostico import ClassificacaoDiagnosticoResumo


class RotuloDatasetCreate(BaseModel):
    classificacao: str = Field(min_length=1, max_length=50)
    version: int = Field(ge=0)


class RotuloDatasetAutor(BaseModel):
    papel: Literal["admin"] = "admin"
    nome: str


class RotuloDatasetItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    diagnostico_id: int
    version: int
    classificacao: ClassificacaoDiagnosticoResumo
    autor: RotuloDatasetAutor
    criado_em: datetime


class RotuloDatasetInfo(BaseModel):
    atual: RotuloDatasetItem | None
    historico: list[RotuloDatasetItem]
    fonte_efetiva: Literal["hality", "profissional", "ia"]
    exportavel: bool
    motivo: str | None = None


FonteRotulo = Literal["hality", "profissional", "ia"]
MotivoInelegivel = Literal["nao_concluido", "sem_imagem", "sem_rotulo_humano", "sem_consentimento"]


class ElegibilidadeDataset(BaseModel):
    """Se o diagnóstico entra hoje numa exportação, com as regras da própria exportação."""

    exportavel: bool
    fonte_efetiva: FonteRotulo
    motivo: MotivoInelegivel | None
