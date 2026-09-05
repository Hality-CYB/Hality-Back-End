"""Vínculo opcional entre paciente e profissional."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PacienteProfissional(Base):
    """Tabela `pacientes_profissionais`."""

    __tablename__ = "pacientes_profissionais"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    profissional_id: Mapped[int] = mapped_column(
        ForeignKey("profissionais.usuario_id", ondelete="CASCADE")
    )
    data_vinculo: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
