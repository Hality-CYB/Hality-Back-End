"""Contratos de leitura administrativa de diagnósticos.

A lista não traz dado clínico. O detalhe traz a foto (URL assinada) e as
respostas da anamnese, que o admin usa para rotular e reclassificar; cada
abertura do detalhe fica na auditoria. A revisão histórica é somente leitura e
preserva a ordem das versões gravadas.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.diagnostico import (
    AnamneseDiagnostico,
    ClassificacaoDiagnosticoResumo,
    ImagemDiagnostico,
    OrigemResultadoInfo,
    StatusDiagnostico,
)
from app.schemas.rotulo_dataset import ElegibilidadeDataset, RotuloDatasetInfo

MOTIVO_IMAGEM_INDISPONIVEL = "politica_de_acesso_pendente"
MOTIVO_DATASET_INDISPONIVEL = "exportacao_fora_do_escopo"


class PacienteAdminResumo(BaseModel):
    id: uuid.UUID
    nome: str


class ClassificacaoAutomatica(BaseModel):
    """Saída da IA. Pode ser nula (diagnóstico `processando` ou `falha`)."""

    classificacao: ClassificacaoDiagnosticoResumo | None
    escala_saburra: int | None
    confianca_ia: float | None
    origem: OrigemResultadoInfo | None


class RevisaoResumo(BaseModel):
    status: Literal["pendente", "concluida"]
    profissional_revisor_id: uuid.UUID | None
    profissional_revisor_nome: str | None
    data_revisao: datetime | None
    classificacao: ClassificacaoDiagnosticoResumo | None
    observacoes: str | None


class RevisaoHistorica(BaseModel):
    profissional_revisor_id: uuid.UUID
    profissional_revisor_nome: str | None
    data_revisao: datetime
    classificacao: ClassificacaoDiagnosticoResumo
    observacoes: str | None


class AdminDiagnosticoItem(BaseModel):
    id: int
    paciente_id: uuid.UUID
    paciente: PacienteAdminResumo
    data: datetime
    status: StatusDiagnostico
    automatica: ClassificacaoAutomatica
    revisao: RevisaoResumo
    qtd_imagens: int
    dataset: ElegibilidadeDataset


class AdminDiagnosticoListResponse(BaseModel):
    itens: list[AdminDiagnosticoItem]
    # Desligada por padrão (DATASET_EXPORT_ENABLED); a tela avisa antes de selecionar.
    exportacao_habilitada: bool
    pagina: int
    limite: int
    total: int
    total_paginas: int


class RevisaoProfissional(BaseModel):
    """Validação clínica feita por um profissional. Não é rótulo de treino."""

    status: Literal["pendente", "concluida"]
    profissional_revisor_id: uuid.UUID | None
    profissional_revisor_nome: str | None
    data_revisao: datetime | None
    classificacao: ClassificacaoDiagnosticoResumo | None
    observacoes: str | None


class DatasetInfo(BaseModel):
    disponivel: bool
    motivo: str | None = MOTIVO_DATASET_INDISPONIVEL


class ReclassificacaoInfo(BaseModel):
    """O que a tela precisa para o admin reclassificar o diagnóstico."""

    version: int
    revisada_por_profissional: bool


class ImagemInfo(BaseModel):
    disponivel: bool = False
    motivo: str | None = MOTIVO_IMAGEM_INDISPONIVEL


class AdminDiagnosticoDetalhe(BaseModel):
    id: int
    paciente_id: uuid.UUID
    paciente: PacienteAdminResumo
    data: datetime
    status: StatusDiagnostico
    erro: str | None
    erro_codigo: str | None
    automatica: ClassificacaoAutomatica
    revisao: RevisaoProfissional
    historico_revisoes: list[RevisaoHistorica]
    dataset: DatasetInfo
    rotulo_dataset: RotuloDatasetInfo
    reclassificacao: ReclassificacaoInfo
    anamnese_id: int | None
    qtd_imagens: int
    imagem: ImagemInfo
    imagens: list[ImagemDiagnostico]
    anamnese: AnamneseDiagnostico | None
