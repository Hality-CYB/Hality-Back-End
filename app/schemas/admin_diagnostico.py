"""Contratos da consulta administrativa de diagnósticos (US-120).

Princípios (DELTA-08):
- Lista SEM imagem e SEM anamnese.
- Detalhe expõe só o contexto necessário à curadoria.
- Classificação automática, revisão profissional e dataset são blocos
  DISTINTOS — nunca um campo único que misture os três.
- Nada aqui representa rótulo de treino: sem DEC-04/DEC-07 ele não existe.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.diagnostico import ClassificacaoDiagnosticoResumo, StatusDiagnostico

MOTIVO_DATASET_INDISPONIVEL = "pendente de decisão DEC-04/DEC-07"


class AdminDiagnosticoItem(BaseModel):
    id: int
    paciente_id: uuid.UUID
    data_diagnostico: datetime
    status: StatusDiagnostico
    classificacao: ClassificacaoDiagnosticoResumo | None  # automática (IA)
    tem_revisao: bool


class AdminDiagnosticoListResponse(BaseModel):
    itens: list[AdminDiagnosticoItem]
    pagina: int
    limite: int
    total: int
    total_paginas: int


class ClassificacaoAutomatica(BaseModel):
    """Saída da IA. Pode ser nula (diagnóstico `processando` ou `falha`)."""

    classificacao: ClassificacaoDiagnosticoResumo | None
    escala_saburra: int | None
    confianca_ia: float | None


class RevisaoProfissional(BaseModel):
    """Validação clínica feita por um profissional. Não é rótulo de treino."""

    profissional_revisor_id: uuid.UUID
    data_revisao: datetime
    observacoes: str | None


class DatasetInfo(BaseModel):
    """Situação do diagnóstico frente a um futuro dataset.

    Fixo em "indisponível" até DEC-04/DEC-07: não há rótulo, curadoria
    mutável nem exportação.
    """

    disponivel: bool = False
    motivo: str = MOTIVO_DATASET_INDISPONIVEL


class AdminDiagnosticoDetalhe(BaseModel):
    id: int
    paciente_id: uuid.UUID
    data_diagnostico: datetime
    status: StatusDiagnostico
    erro: str | None
    automatica: ClassificacaoAutomatica
    revisao: RevisaoProfissional | None
    dataset: DatasetInfo
    anamnese_id: int  # só a referência; respostas NÃO são expostas
    qtd_imagens: int  # só a contagem; URLs NÃO são expostas
