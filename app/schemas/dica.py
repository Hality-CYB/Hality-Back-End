from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CategoriaDica(StrEnum):
    HIGIENE = "higiene"
    SAUDE = "saude"
    NUTRICAO = "nutricao"
    ROTINA = "rotina"
    ESTILO_DE_VIDA = "estilo_de_vida"
    DIETA = "dieta"
    TRATAMENTO = "tratamento"


class TipoConteudoDica(StrEnum):
    TEXTO = "texto"
    IMAGEM = "imagem"
    VIDEO = "video"


class StatusDica(StrEnum):
    RASCUNHO = "rascunho"
    PUBLICADO = "publicado"


class ConteudoTexto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texto: str


class ConteudoArquivo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_url: str
    descricao: str


class DicaBase(BaseModel):
    titulo: str
    categoria: CategoriaDica
    tipo_conteudo: TipoConteudoDica
    conteudo: ConteudoTexto | ConteudoArquivo
    classificacao_ids: list[int] = Field(default_factory=list)
    aparece_na_home: bool = False
    status: StatusDica = StatusDica.RASCUNHO
    ordem: int = 0

    @model_validator(mode="after")
    def validar_conteudo(self) -> "DicaBase":
        eh_texto = isinstance(self.conteudo, ConteudoTexto)
        if self.tipo_conteudo == TipoConteudoDica.TEXTO and not eh_texto:
            raise ValueError("conteudo deve conter apenas texto para tipo_conteudo texto")
        if self.tipo_conteudo != TipoConteudoDica.TEXTO and eh_texto:
            raise ValueError(
                "conteudo deve conter file_url e descricao para tipo_conteudo imagem ou video"
            )
        return self


class DicaCreate(DicaBase):
    pass


class DicaDetail(DicaBase):
    id: int