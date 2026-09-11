"""Questionário de anamnese versionado, fonte real do catálogo ativo."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Questionario(Base):
    """Tabela `questionarios`.

    `perguntas` guarda uma lista de objetos no mesmo formato do schema
    `Pergunta` (app/schemas/anamnese.py): id, enunciado, tipo, obrigatoria,
    opcoes, escala_min, escala_max, escala_label_min, escala_label_max.

    A versão vigente é a de `criado_em` mais recente. Se a tabela estiver
    vazia (ou a consulta falhar), `anamnese_questionnaire.py` cai pro
    catálogo estático como fallback - a aplicação nunca fica sem questionário.
    """

    __tablename__ = "questionarios"

    versao: Mapped[str] = mapped_column(String(50), primary_key=True)
    perguntas: Mapped[list[dict]] = mapped_column(JSONB)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
