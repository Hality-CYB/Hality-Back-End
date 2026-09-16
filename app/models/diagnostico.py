"""Diagnóstico gerado pela IA a partir das imagens enviadas pelo paciente."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Diagnostico(Base):
    __tablename__ = "diagnosticos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    anamnese_id: Mapped[int] = mapped_column(
        ForeignKey("anamneses.id", ondelete="CASCADE"), unique=True
    )
    classificacao_id: Mapped[int | None] = mapped_column(
        ForeignKey("classificacoes_diagnostico.id"), nullable=True
    )
    escala_saburra: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confianca_ia: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="processando")
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_diagnostico: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    data_envio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_processamento: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    profissional_revisor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    data_revisao: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observacoes_revisao: Mapped[str | None] = mapped_column(Text, nullable=True)
    interesse_consulta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
