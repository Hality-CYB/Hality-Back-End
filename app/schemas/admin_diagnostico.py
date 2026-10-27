"""Contratos de leitura administrativa de diagnósticos.

As respostas não expõem respostas de anamnese, URLs de imagens ou dados de
exportação. A revisão histórica é somente leitura e preserva a ordem das
versões gravadas.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.diagnostico import (
    ClassificacaoDiagnosticoResumo,
    OrigemResultadoInfo,
    StatusDiagnostico,
)
from app.schemas.rotulo_dataset import RotuloDatasetInfo

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


class AdminDiagnosticoListResponse(BaseModel):
    itens: list[AdminDiagnosticoItem]
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
    """Situação do diagnóstico frente à exportação de dataset.

    A exportação não faz parte deste recurso; os rótulos Hality ficam em
    ``rotulo_dataset``.
    """

    disponivel: bool = False
    motivo: str = MOTIVO_DATASET_INDISPONIVEL


class ImagemInfo(BaseModel):
    disponivel: bool = False
    motivo: str = MOTIVO_IMAGEM_INDISPONIVEL


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
    anamnese_id: int | None
    qtd_imagens: int
    imagem: ImagemInfo
