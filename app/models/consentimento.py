"""Trilha append-only de decisões de consentimento por finalidade (US-020)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConsentimentoEvento(Base):
    """Tabela `consentimento_eventos`.

    Cada linha é UMA decisão (aceite ou recusa/revogação) do titular para uma
    finalidade e uma versão do termo. Nunca é atualizada nem apagada: o estado
    vigente é o evento mais recente da finalidade, e revogar é gravar um novo
    evento com `aceito = false`. Não guarda texto do termo nem dado clínico.

    `titular_id` usa RESTRICT: o histórico é a prova da decisão e não pode
    sumir junto com a exclusão do usuário sem uma política de retenção
    explícita. `ator_id` usa SET NULL, como em `auditoria_acessos`.
    """

    __tablename__ = "consentimento_eventos"
    __table_args__ = (
        CheckConstraint(
            "finalidade IN ('health_data', 'image_training')",
            name="ck_consentimento_eventos_finalidade",
        ),
        Index("ix_consentimento_eventos_titular_finalidade", "titular_id", "finalidade", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    titular_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    finalidade: Mapped[str] = mapped_column(String(30))
    versao: Mapped[str] = mapped_column(String(20))
    aceito: Mapped[bool] = mapped_column(Boolean)
    origem: Mapped[str] = mapped_column(String(30))
    ator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    ator_papel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    referencia_coleta: Mapped[str | None] = mapped_column(String(128), nullable=True)
    registrado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
