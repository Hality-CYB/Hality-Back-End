"""Solicitações públicas não concedem identidade nem acesso clínico."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SolicitacaoProfissional(Base):
    __tablename__ = "solicitacoes_profissionais"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pendente', 'aprovada', 'recusada')", name="ck_solicitacao_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    nome: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    telefone: Mapped[str | None] = mapped_column(String(20))
    registro_profissional: Mapped[str] = mapped_column(String(50))
    especialidade: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default="pendente", index=True)
    termos_aceitos_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )
    decidido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decidido_por: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
