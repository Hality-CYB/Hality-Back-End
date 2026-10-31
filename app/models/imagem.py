"""Imagem enviada pelo paciente, usada para gerar um diagnóstico."""

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Imagem(Base):
    __tablename__ = "imagens"
    __table_args__ = (
        UniqueConstraint("diagnostico_id", "ordem", name="uq_imagens_diagnostico_ordem"),
        CheckConstraint(
            "tamanho_bytes IS NULL OR tamanho_bytes > 0",
            name="ck_imagens_tamanho_positivo",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    diagnostico_id: Mapped[int] = mapped_column(ForeignKey("diagnosticos.id", ondelete="CASCADE"))
    url_arquivo: Mapped[str] = mapped_column(String(500))
    ordem: Mapped[int] = mapped_column(Integer)
    parametros_captura: Mapped[dict] = mapped_column(JSONB)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tamanho_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_captura: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
