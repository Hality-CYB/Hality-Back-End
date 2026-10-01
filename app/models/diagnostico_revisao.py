import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DiagnosticoRevisao(Base):
    __tablename__ = "diagnostico_revisoes"

    __table_args__ = (
        UniqueConstraint(
            "diagnostico_id",
            "versao",
            name="uq_diagnostico_revisoes_diagnostico_versao",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    diagnostico_id: Mapped[int] = mapped_column(
        ForeignKey("diagnosticos.id", ondelete="CASCADE"),
        nullable=False,
    )

    profissional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    classificacao_id: Mapped[int] = mapped_column(
        ForeignKey("classificacoes_diagnostico.id"),
        nullable=False,
    )

    observacao: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    versao: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    revisao_anterior_id: Mapped[int | None] = mapped_column(
        ForeignKey("diagnostico_revisoes.id"),
        nullable=True,
    )

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
