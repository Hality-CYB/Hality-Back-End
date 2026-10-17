"""Identidade de um provedor externo (ex.: Google) vinculada a um usuário."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IdentidadeExterna(Base):
    """Tabela `identidades_externas`.

    A chave do vínculo é (`provider`, `subject`) — o `sub` imutável do provedor —
    e nunca o e-mail, que pode mudar ou ser reaproveitado. Um usuário tem no
    máximo uma identidade por provedor. Não guarda token nem perfil bruto.
    """

    __tablename__ = "identidades_externas"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_identidades_externas_provider_subject"),
        UniqueConstraint("user_id", "provider", name="uq_identidades_externas_user_provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(255))
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    ultimo_login_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
