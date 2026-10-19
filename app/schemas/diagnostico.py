import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class StatusDiagnostico(StrEnum):
    """Estados do processamento do diagnóstico (semântica no README).

    A revisão profissional não é um estado concorrente: ela é representada
    separadamente por `revisao`/`tem_revisao`.
    """

    PROCESSANDO = "processando"
    AGUARDANDO_REVISAO = "aguardando_revisao"
    CONCLUIDO = "concluido"
    FALHA = "falha"


STATUS_COM_RESULTADO = frozenset(
    {
        StatusDiagnostico.AGUARDANDO_REVISAO.value,
        StatusDiagnostico.CONCLUIDO.value,
    }
)


class OrigemResultado(StrEnum):
    LEGADO = "legado"
    MOCK = "mock"
    MODELO = "modelo"


class OrigemResultadoInfo(BaseModel):
    tipo: OrigemResultado
    provider: str | None
    versao: str | None


class ClassificacaoDiagnosticoResumo(BaseModel):
    codigo: str
    nome_exibicao: str
    ordem: int


class ClassificacaoDiagnosticoDetalhe(ClassificacaoDiagnosticoResumo):
    id: int


class DiagnosticoListItem(BaseModel):
    id: int
    data_diagnostico: datetime
    status: StatusDiagnostico
    classificacao: ClassificacaoDiagnosticoResumo | None
    escala_saburra: int | None


class DiagnosticoListResponse(BaseModel):
    itens: list[DiagnosticoListItem]
    pagina: int
    limite: int
    total: int
    total_paginas: int


class DiagnosticoCriadoResponse(BaseModel):
    id: int
    status: StatusDiagnostico
    data_diagnostico: datetime
    anamnese_id: int


class ImagemDiagnostico(BaseModel):
    id: int
    url_arquivo: str
    ordem: int
    data_captura: datetime


class AnamneseDiagnostico(BaseModel):
    id: int
    paciente_id: uuid.UUID
    data_preenchimento: datetime
    versao_questionario: str
    respostas: list[dict[str, Any]]


class RevisaoDiagnosticoPaciente(BaseModel):
    profissional_nome: str | None
    data_revisao: datetime | None
    observacoes: str | None
    nivel_corrigido: bool
    classificacao: ClassificacaoDiagnosticoDetalhe | None
    version: int


class ConteudoDiagnostico(BaseModel):
    id: int
    conteudo: dict[str, Any]
    titulo: str


class DiagnosticoPacienteDetalhe(BaseModel):
    id: int
    data_diagnostico: datetime
    status: StatusDiagnostico
    classificacao: ClassificacaoDiagnosticoDetalhe | None
    escala_saburra: int | None
    confianca_ia: float | None
    imagens: list[ImagemDiagnostico]
    anamnese: AnamneseDiagnostico
    revisao: RevisaoDiagnosticoPaciente | None
    tem_profissional_vinculado: bool
    conteudos: list[ConteudoDiagnostico]
    aviso_legal: str
    erro: str | None
    erro_codigo: str | None
