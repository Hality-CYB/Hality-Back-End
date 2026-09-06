"""Imagem enviada pelo paciente, usada para gerar um diagnóstico."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Imagem(Base):
    """Tabela `imagens`: um diagnóstico pode ter mais de uma imagem."""

    __tablename__ = "imagens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    diagnostico_id: Mapped[int] = mapped_column(ForeignKey("diagnosticos.id", ondelete="CASCADE"))
    url_arquivo: Mapped[str] = mapped_column(String(500))
    ordem: Mapped[int] = mapped_column(Integer)
    data_captura: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
