"""Diagnóstico gerado pela IA a partir das imagens enviadas pelo paciente."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Diagnostico(Base):
    """Tabela `diagnosticos`.

    `paciente_id` é o titular; `executor_id` é quem enviou a imagem (o próprio
    paciente ou o profissional vinculado). Nulo = registro legado.

    `erro` é detalhe técnico interno e nunca vai para a API; o que sai é
    `erro_codigo`. As colunas de revisão são só um snapshot da última versão
    em `diagnostico_revisoes`.
    """

    __tablename__ = "diagnosticos"
    __table_args__ = (
        Index("ix_diagnosticos_data_diagnostico_id", "data_diagnostico", "id"),
        CheckConstraint(
            "status IN ('processando', 'aguardando_revisao', 'concluido', 'falha')",
            name="ck_diagnosticos_status",
        ),
        CheckConstraint(
            "origem_resultado IN ('legado', 'mock', 'modelo')",
            name="ck_diagnosticos_origem_resultado",
        ),
        CheckConstraint(
            # IS NOT DISTINCT FROM: com origem nula, `=` daria NULL e o CHECK passaria.
            "origem_resultado IS NOT DISTINCT FROM 'modelo' "
            "OR (modelo_provider IS NULL AND modelo_versao IS NULL)",
            name="ck_diagnosticos_modelo_somente_inferencia",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paciente_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # NO ACTION (não RESTRICT): o CASCADE de `users` ainda apaga os dois juntos.
    anamnese_id: Mapped[int] = mapped_column(ForeignKey("anamneses.id"), unique=True)
    executor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    classificacao_id: Mapped[int | None] = mapped_column(
        ForeignKey("classificacoes_diagnostico.id"), nullable=True
    )
    escala_saburra: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confianca_ia: Mapped[float | None] = mapped_column(Float, nullable=True)
    origem_resultado: Mapped[str | None] = mapped_column(String(20), nullable=True)
    modelo_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    modelo_versao: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="processando")
    erro_codigo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_diagnostico: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    profissional_revisor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    data_revisao: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observacoes_revisao: Mapped[str | None] = mapped_column(Text, nullable=True)
    interesse_consulta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
