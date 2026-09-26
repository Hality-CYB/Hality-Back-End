"""Vínculo opcional entre paciente e profissional.

Só vínculo com ``ativo = True`` dá ao profissional acesso aos dados clínicos do
paciente (ver ``app/auth/policies.py``).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PacienteProfissional(Base):
    """Tabela `pacientes_profissionais`."""

    __tablename__ = "pacientes_profissionais"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paciente_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    profissional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profissionais.usuario_id", ondelete="CASCADE")
    )
    data_vinculo: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
