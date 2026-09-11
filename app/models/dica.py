"""Conteúdo educativo sobre halitose exibido na home do app."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Dica(Base):
    """Tabela `dicas`.

    Material educativo mostrado na home do app, com `titulo` curto e
    `conteudo` em texto livre. Não se relaciona com nenhuma outra tabela.
    """

    __tablename__ = "dicas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    titulo: Mapped[str] = mapped_column(String(255))
    conteudo: Mapped[str] = mapped_column(Text)
