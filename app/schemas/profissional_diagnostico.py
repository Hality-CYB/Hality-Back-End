import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.diagnostico import ClassificacaoDiagnosticoResumo

MAX_OBSERVACAO_REVISAO = 2000


class PacienteDiagnosticoResumo(BaseModel):
    id: uuid.UUID
    nome: str


class RevisaoProfissionalListagem(BaseModel):
    version: int
    classificacao: ClassificacaoDiagnosticoResumo


class DiagnosticoProfissionalItem(BaseModel):
    id: int
    paciente: PacienteDiagnosticoResumo
    data_diagnostico: datetime
    status: str
    classificacao_automatica: ClassificacaoDiagnosticoResumo | None
    tem_revisao: bool
    revisao: RevisaoProfissionalListagem | None = None


class DiagnosticoProfissionalListResponse(BaseModel):
    itens: list[DiagnosticoProfissionalItem]
    pagina: int
    limite: int
    total: int
    total_paginas: int


class AnamneseDiagnosticoProfissional(BaseModel):
    id: int
    data_preenchimento: datetime
    respostas: list[dict[str, Any]]


class ImagemDiagnosticoProfissional(BaseModel):
    id: int
    url_arquivo: str
    ordem: int
    data_captura: datetime


class ResultadoAutomaticoDiagnostico(BaseModel):
    classificacao: ClassificacaoDiagnosticoResumo | None
    escala_saburra: int | None
    confianca_ia: float | None


class RevisaoProfissionalResumo(BaseModel):
    id: int
    version: int
    classificacao: ClassificacaoDiagnosticoResumo
    profissional_id: uuid.UUID
    profissional_nome: str | None
    observacao: str | None
    criado_em: datetime


class DiagnosticoProfissionalDetalhe(BaseModel):
    id: int
    data_diagnostico: datetime
    status: str
    paciente: PacienteDiagnosticoResumo
    anamnese: AnamneseDiagnosticoProfissional
    imagens: list[ImagemDiagnosticoProfissional]
    automatico: ResultadoAutomaticoDiagnostico | None
    revisao: RevisaoProfissionalResumo | None
    historico_revisoes: list[RevisaoProfissionalResumo]
    version: int
    aviso_legal: str
    erro: str | None = None


class RevisaoProfissionalInput(BaseModel):
    classificacao: str = Field(
        min_length=1,
        max_length=50,
        description="Código canônico da classificação.",
    )
    observacao: str | None = Field(
        default=None,
        max_length=MAX_OBSERVACAO_REVISAO,
    )
    version: int = Field(
        ge=0,
        description="Versão atual conhecida pelo cliente.",
    )


class RevisaoProfissionalResponse(BaseModel):
    revisao: RevisaoProfissionalResumo
    version: int
