"""cria a tabela genérica de conteúdos"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "e7c1d2a3b4f5"
down_revision = "2ab18391a8a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade():
    op.execute(sa.text("DROP TABLE IF EXISTS conteudos_diagnostico CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS dicas CASCADE"))
    for values, name in [
        (
            "'higiene','saude','nutricao','rotina','estilo_de_vida','dieta','tratamento'",
            "categoria_dica",
        ),
        ("'rascunho','publicado'", "status_dica"),
    ]:
        op.execute(sa.text(f"CREATE TYPE {name} AS ENUM ({values})"))
    op.create_table(
        "conteudos",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("titulo", sa.String(255), nullable=False),
        sa.Column(
            "categoria", postgresql.ENUM(name="categoria_dica", create_type=False), nullable=False
        ),
        sa.Column("conteudo", postgresql.JSONB, nullable=False),
        sa.Column(
            "classificacao_ids",
            postgresql.ARRAY(sa.Integer),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
        sa.Column("aparece_na_home", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="status_dica", create_type=False),
            server_default=sa.text("'rascunho'"),
            nullable=False,
        ),
        sa.Column("ordem", sa.Integer, server_default=sa.text("0"), nullable=False),
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
    )
    op.create_index(
        "ix_conteudos_classificacao_ids", "conteudos", ["classificacao_ids"], postgresql_using="gin"
    )


def downgrade():
    op.drop_index("ix_conteudos_classificacao_ids", table_name="conteudos")
    op.drop_table("conteudos")
    for name in ("status_dica", "categoria_dica"):
        op.execute(sa.text(f"DROP TYPE {name}"))
