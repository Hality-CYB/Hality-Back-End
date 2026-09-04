from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

StatusDiagnostico = Literal[
    "processando",
    "aguardando_analise",
    "aguardando_revisao",
    "concluido",
    "falha",
]


class ParametrosCaptura(BaseModel):
    model_config = ConfigDict(extra="allow")

    flash: bool | None = None
    orientacao: str | None = None
    device: str | None = None


class DiagnosticoPostResponse(BaseModel):
    id: int
    status: StatusDiagnostico
    data_diagnostico: datetime
    anamnese_id: int


class ClassificacaoDiagnosticoResponse(BaseModel):
    id: int
    codigo: str
    nome_exibicao: str
    ordem: int


class ImagemDiagnosticoResponse(BaseModel):
    id: int
    url_arquivo: str
    ordem: int
    data_captura: datetime


class RespostaAnamneseResponse(BaseModel):
    pergunta_id: str
    enunciado: str
    tipo: str
    valor: Any


class AnamneseDiagnosticoResponse(BaseModel):
    id: int
    data_preenchimento: datetime
    respostas: list[RespostaAnamneseResponse]


class RevisaoDiagnosticoResponse(BaseModel):
    revisado: bool
    profissional_nome: str | None = None
    data_revisao: datetime | None = None
    observacoes: str | None = None
    nivel_corrigido: bool | None = None


class ConteudoDadosResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    icone: str
    corpo: str


class ConteudoDiagnosticoResponse(BaseModel):
    id: int
    tipo: str
    titulo: str
    dados: ConteudoDadosResponse


class DiagnosticoGetResponse(BaseModel):
    id: int
    data_diagnostico: datetime
    status: StatusDiagnostico

    classificacao: ClassificacaoDiagnosticoResponse | None = None

    escala_saburra: int | None = Field(
        default=None,
        ge=0,
        le=100,
    )

    confianca_ia: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )

    imagens: list[ImagemDiagnosticoResponse]
    anamnese: AnamneseDiagnosticoResponse

    revisao: RevisaoDiagnosticoResponse | None = None

    tem_profissional_vinculado: bool

    conteudos: list[ConteudoDiagnosticoResponse]

    aviso_legal: str

    erro: str | None = None