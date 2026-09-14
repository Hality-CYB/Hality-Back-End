"""cria tabela dicas

Revision ID: b4c99c48b0f2
Revises: 652cbc54920d
Create Date: 2026-09-11 20:19:42.431135

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b4c99c48b0f2"
down_revision: str | None = "652cbc54920d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    categoria_dica = postgresql.ENUM(
        "higiene",
        "saude",
        "nutricao",
        "rotina",
        "estilo_de_vida",
        "dieta",
        "tratamento",
        name="categoria_dica",
        create_type=False,
    )
    tipo_conteudo_dica = postgresql.ENUM(
        "texto", "imagem", "video", name="tipo_conteudo_dica", create_type=False
    )
    status_dica = postgresql.ENUM(
        "rascunho", "publicado", name="status_dica", create_type=False
    )
    bind = op.get_bind()
    categoria_dica.create(bind)
    tipo_conteudo_dica.create(bind)
    status_dica.create(bind)

    op.create_table(
        "dicas",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("titulo", sa.String(length=255), nullable=False),
        sa.Column("categoria", categoria_dica, nullable=False),
        sa.Column("tipo_conteudo", tipo_conteudo_dica, nullable=False),
        sa.Column("conteudo", postgresql.JSONB(), nullable=False),
        sa.Column(
            "classificacao_ids",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
        sa.Column(
            "aparece_na_home", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "status", status_dica, server_default=sa.text("'rascunho'"), nullable=False
        ),
        sa.Column("ordem", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dicas_classificacao_ids",
        "dicas",
        ["classificacao_ids"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_dicas_classificacao_ids", table_name="dicas")
    op.drop_table("dicas")
    bind = op.get_bind()
    for enum_name in ("status_dica", "tipo_conteudo_dica", "categoria_dica"):
        postgresql.ENUM(name=enum_name).drop(bind)
