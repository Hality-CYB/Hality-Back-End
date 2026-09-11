from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class TipoPergunta(StrEnum):
    BOOLEAN = "boolean"
    SINGLE_CHOICE = "single_choice"
    TEXT = "text"
    SCALE = "scale"


class Pergunta(BaseModel):
    id: str
    enunciado: str
    tipo: TipoPergunta
    obrigatoria: bool = True
    opcoes: list[str] | None = None
    escala_min: int | None = None
    escala_max: int | None = None
    escala_label_min: str | None = None
    escala_label_max: str | None = None


class Questionario(BaseModel):
    versao: str
    perguntas: list[Pergunta]


class RespostaItem(BaseModel):
    pergunta_id: str
    enunciado: str
    tipo: TipoPergunta
    valor: bool | str | int


class AnamneseCreate(BaseModel):
    versao_questionario: str
    respostas: list[RespostaItem]


class AnamneseCreated(BaseModel):
    """Corpo de resposta do POST, exatamente como especificado na issue #18."""

    id: int
    paciente_id: int
    data_preenchimento: datetime


class AnamneseDetail(BaseModel):
    """Usado nos GETs/PUT do CRUD, onde faz sentido devolver o conteúdo completo."""

    id: int
    paciente_id: int
    data_preenchimento: datetime
    versao_questionario: str
    respostas: list[RespostaItem]
