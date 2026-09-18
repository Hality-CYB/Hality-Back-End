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
    titulo: str = Field(max_length=255)
    categoria: CategoriaConteudo
    conteudo: ConteudoSchema
    classificacao_ids: list[int] = []
    aparece_na_home: bool = False
    status: StatusConteudo = StatusConteudo.RASCUNHO
    ordem: int = 0


class ConteudoDetail(ConteudoCreate):
    id: int
