"""Conteúdo educativo sobre halitose exibido no app."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import ARRAY, Boolean, DateTime, Enum, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CategoriaDica(StrEnum):
    HIGIENE = "higiene"
    SAUDE = "saude"
    NUTRICAO = "nutricao"
    ROTINA = "rotina"
    ESTILO_DE_VIDA = "estilo_de_vida"
    DIETA = "dieta"
    TRATAMENTO = "tratamento"


class TipoConteudoDica(StrEnum):
    TEXTO = "texto"
    IMAGEM = "imagem"
    VIDEO = "video"


class StatusDica(StrEnum):
    RASCUNHO = "rascunho"
    PUBLICADO = "publicado"


class Dica(Base):
    """Material educativo mostrado na home e/ou nas orientações do app."""

    __tablename__ = "dicas"
    __table_args__ = (
        Index("ix_dicas_classificacao_ids", "classificacao_ids", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    titulo: Mapped[str] = mapped_column(String(255))
    categoria: Mapped[CategoriaDica] = mapped_column(
        Enum(
            CategoriaDica,
            name="categoria_dica",
            values_callable=lambda enum_type: [item.value for item in enum_type],
        )
    )
    tipo_conteudo: Mapped[TipoConteudoDica] = mapped_column(
        Enum(
            TipoConteudoDica,
            name="tipo_conteudo_dica",
            values_callable=lambda enum_type: [item.value for item in enum_type],
        )
    )
    conteudo: Mapped[dict] = mapped_column(JSONB)
    classificacao_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=text("'{}'::integer[]")
    )
    aparece_na_home: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false")
    )
    status: Mapped[StatusDica] = mapped_column(
        Enum(
            StatusDica,
            name="status_dica",
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        server_default=text("'rascunho'"),
    )
    ordem: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
