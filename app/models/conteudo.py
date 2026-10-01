"""Conteúdo informativo genérico exibido no aplicativo."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
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
    # Criados nas migrations e7c1d2a3b4f5 (índice GIN) e a82d5d4b3f10 (regra de
    # publicação); declarados aqui para o autogenerate não propor removê-los.
    __table_args__ = (
        Index("ix_conteudos_classificacao_ids", "classificacao_ids", postgresql_using="gin"),
        CheckConstraint(
            "status <> 'publicado' OR "
            "(criado_por_id IS NOT NULL AND publicado_por_id IS NOT NULL "
            "AND publicado_em IS NOT NULL)",
            name="ck_conteudos_publicado_com_owner",
        ),
    )
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
    criado_por_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    atualizado_por_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    publicado_por_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
