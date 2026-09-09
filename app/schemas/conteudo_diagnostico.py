from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class TipoConteudo(StrEnum):
    DICA = "dica"
    PROTOCOLO = "protocolo"


class DadosDica(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo_midia: str = Field(min_length=1)
    corpo: str = Field(min_length=1)


class DadosProtocolo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numero_sessoes: int = Field(ge=1)
    descricao: str = Field(min_length=1)


_SCHEMA_POR_TIPO: dict[TipoConteudo, type[BaseModel]] = {
    TipoConteudo.DICA: DadosDica,
    TipoConteudo.PROTOCOLO: DadosProtocolo,
}


class ConteudoDiagnosticoCreate(BaseModel):
    """[substituiu protocolos_tratamento + dicas_tratamento - sugestao Discord]

    `classificacao_id` = None quando o conteúdo é genérico, não ligado a uma
    classificação de diagnóstico específica. O formato de `dados` depende de
    `tipo`: é validado contra `DadosDica` ou `DadosProtocolo` (dispatch por
    tipo) e armazenado já normalizado como dict.
    """

    classificacao_id: int | None = None
    tipo: TipoConteudo
    titulo: str = Field(min_length=1)
    dados: dict[str, Any]  

    @field_validator("dados", mode="after")
    @classmethod
    def validar_dados_por_tipo(cls, dados: dict[str, Any], info: ValidationInfo) -> dict[str, Any]:
        tipo = info.data.get("tipo")
        schema_cls = _SCHEMA_POR_TIPO[tipo]
        validado = schema_cls(**dados)
        return validado.model_dump()


class ConteudoDiagnosticoDetail(ConteudoDiagnosticoCreate):
    id: int
