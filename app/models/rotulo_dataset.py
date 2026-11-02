"""Rótulos de curadoria Hality, mantidos como histórico append-only."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RotuloDataset(Base):
    __tablename__ = "rotulos_dataset"
    __table_args__ = (
        UniqueConstraint(
            "diagnostico_id", "version", name="uq_rotulos_dataset_diagnostico_version"
        ),
        CheckConstraint("version > 0", name="ck_rotulos_dataset_version_positiva"),
        Index("ix_rotulos_dataset_diagnostico_version", "diagnostico_id", "version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    diagnostico_id: Mapped[int] = mapped_column(
        ForeignKey("diagnosticos.id", ondelete="CASCADE"), nullable=False
    )
    admin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    classificacao_id: Mapped[int] = mapped_column(
        ForeignKey("classificacoes_diagnostico.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rotulo_anterior_id: Mapped[int | None] = mapped_column(
        ForeignKey("rotulos_dataset.id"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )
