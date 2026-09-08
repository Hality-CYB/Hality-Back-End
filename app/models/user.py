"""Modelo de usuário — entidade persistida no banco de dados via fastapi-users."""

import uuid

from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    """Tabela `user`: armazena pacientes, profissionais e admins.

    Campos herdados do fastapi-users (SQLAlchemyBaseUserTableUUID):
        id (UUID), email, hashed_password, is_active, is_superuser, is_verified

    Campos customizados:
        name, phone, role
    """

    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="patient")
