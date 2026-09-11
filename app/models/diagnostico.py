"""Diagnóstico gerado pela IA a partir das imagens enviadas pelo paciente."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Diagnostico(Base):
    """Tabela `diagnosticos`.

    `status` segue os valores de `StatusDiagnostico` (schemas/diagnostico.py):
    gerado, em_revisao, revisado. A revisão é feita por um profissional e é
    apenas auditoria/validação clínica - NÃO alimenta retreino do modelo.
    """

    __tablename__ = "diagnosticos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    classificacao_id: Mapped[int] = mapped_column(ForeignKey("classificacoes_diagnostico.id"))
    escala_saburra: Mapped[int] = mapped_column(Integer)
    confianca_ia: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="gerado")
    data_diagnostico: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    profissional_revisor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    data_revisao: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observacoes_revisao: Mapped[str | None] = mapped_column(Text, nullable=True)
    interesse_consulta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
