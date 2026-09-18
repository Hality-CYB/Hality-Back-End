"""Conteudo informativo generico exibido no aplicativo."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CategoriaConteudo(StrEnum):
    HIGIENE = "higiene"
    SAUDE = "saude"
    NUTRICAO = "nutricao"
    ROTINA = "rotina"
    ESTILO_DE_VIDA = "estilo_de_vida"
    DIETA = "dieta"
    TRATAMENTO = "tratamento"


class StatusConteudo(StrEnum):
    RASCUNHO = "rascunho"
    PUBLICADO = "publicado"


class Conteudo(Base):
    __tablename__ = "conteudos"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    titulo: Mapped[str] = mapped_column(String(255), nullable=False)
    categoria: Mapped[CategoriaConteudo] = mapped_column(
        Enum(
            CategoriaConteudo,
            name="categoria_dica",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    conteudo: Mapped[dict] = mapped_column(JSONB, nullable=False)
    classificacao_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'::integer[]")
    )
    aparece_na_home: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    status: Mapped[StatusConteudo] = mapped_column(
        Enum(
            StatusConteudo,
            name="status_dica",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        server_default=text("'rascunho'"),
    )
    ordem: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
