"""Trilha de auditoria de acessos a dados sensíveis (ex.: detalhe de diagnóstico no admin)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditoriaAcesso(Base):
    """Tabela `auditoria_acessos`.

    Registra QUEM (`ator_id`) fez O QUÊ (`acao`) sobre QUAL recurso
    (`recurso_tipo` + `recurso_id`) e QUANDO. Não guarda conteúdo do recurso —
    só a referência — para a própria trilha não virar fonte de dado sensível.

    `ator_id` usa SET NULL para que a exclusão de um usuário (ex.: pedido de
    apagamento) não destrua a trilha nem seja bloqueada por ela.
    """

    __tablename__ = "auditoria_acessos"
    __table_args__ = (
        Index("ix_auditoria_acessos_ator_id", "ator_id"),
        Index("ix_auditoria_acessos_recurso", "recurso_tipo", "recurso_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acao: Mapped[str] = mapped_column(String(50))
    papel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    recurso_tipo: Mapped[str] = mapped_column(String(50))
    recurso_id: Mapped[str] = mapped_column(String(50))
    resultado: Mapped[str] = mapped_column(String(20), default="sucesso", nullable=False)
    metadados: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    chave_operacao: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
