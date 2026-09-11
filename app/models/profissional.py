"""Dados de profissional — extensão de `users` quando role = profissional."""

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Profissional(Base):
    """Tabela `profissionais`: relação um-para-um com `users`."""

    __tablename__ = "profissionais"

    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    registro_profissional: Mapped[str | None] = mapped_column(String(50), nullable=True)
    especialidade: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vinculado_hality: Mapped[bool] = mapped_column(Boolean, default=False)
