"""Modelo de usuário — entidade persistida no banco de dados via SQLAlchemy."""

from datetime import UTC, datetime

from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    """Tabela ``users``: armazena pacientes, profissionais e admins.

    Campos herdados do fastapi-users (SQLAlchemyBaseUserTableUUID):
        id: UUID primário gerado automaticamente.
        email: Endereço de e-mail único (usado como login).
        hashed_password: Hash da senha — nunca a senha em texto plano.
        is_active: Indica se a conta está ativa.
        is_superuser: Indica se é administrador.
        is_verified: Indica se o e-mail foi verificado.

    Campos extras:
        name: Nome completo do usuário.
        phone: Telefone opcional.
        role: Papel do usuário (``patient``, ``professional``, ``admin``).
        created_at: Timestamp de criação da conta.
    """

    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="patient", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
