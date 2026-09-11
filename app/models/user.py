"""Modelo de usuário — entidade persistida no banco de dados via SQLAlchemy."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    """Tabela ``users``: armazena pacientes, profissionais e admins.

    Campos:
        id: UUID primário gerado automaticamente.
        email: Endereço de e-mail único (usado como login).
        hashed_password: Hash bcrypt da senha — nunca a senha em texto plano.
        name: Nome completo do usuário.
        phone: Telefone opcional.
        role: Papel do usuário (``patient``, ``professional``, ``admin``).
        is_active: Indica se a conta está ativa.
        created_at: Timestamp de criação da conta.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="patient", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
