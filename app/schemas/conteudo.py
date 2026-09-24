import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CategoriaConteudo(StrEnum):
    HIGIENE = "higiene"
    SAUDE = "saude"
    NUTRICAO = "nutricao"
    ROTINA = "rotina"
    ESTILO_DE_VIDA = "estilo_de_vida"
    DIETA = "dieta"
    TRATAMENTO = "tratamento"


class StatusConteudo(StrEnum):
    RASCUNHO = "rascunho"
    PUBLICADO = "publicado"


class BlocoConteudo(BaseModel):
    model_config = ConfigDict(extra="allow")
    tipo: str


class ConteudoSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    itens: list[BlocoConteudo] = Field(min_length=1)


class ConteudoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titulo: str = Field(min_length=1, max_length=255)
    categoria: CategoriaConteudo
    conteudo: ConteudoSchema
    classificacao_ids: list[int] = Field(default_factory=list)
    aparece_na_home: bool = False
    status: StatusConteudo = StatusConteudo.RASCUNHO
    ordem: int = Field(default=0, ge=0)


class ConteudoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titulo: str | None = Field(default=None, min_length=1, max_length=255)
    categoria: CategoriaConteudo | None = None
    conteudo: ConteudoSchema | None = None
    classificacao_ids: list[int] | None = None
    aparece_na_home: bool | None = None
    status: StatusConteudo | None = None
    ordem: int | None = Field(default=None, ge=0)


class ConteudoDetail(ConteudoCreate):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int
    created_at: datetime
    updated_at: datetime
    criado_por_id: uuid.UUID | None
    atualizado_por_id: uuid.UUID | None
    publicado_por_id: uuid.UUID | None
    publicado_em: datetime | None
