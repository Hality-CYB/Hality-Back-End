"""adiciona autoria e publicacao a conteudos

Revision ID: a82d5d4b3f10
Revises: 198bcce46c43
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a82d5d4b3f10"
down_revision: str | None = "198bcce46c43"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Conteúdo legado não tem responsável identificável e, portanto, volta
    # para rascunho antes de a regra de publicação ser aplicada.
    op.execute("UPDATE conteudos SET status = 'rascunho'")

    for coluna in ("criado_por_id", "atualizado_por_id", "publicado_por_id"):
        op.add_column(
            "conteudos",
            sa.Column(coluna, postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            f"fk_conteudos_{coluna}_users",
            "conteudos",
            "users",
            [coluna],
            ["id"],
        )

    op.add_column("conteudos", sa.Column("publicado_em", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_conteudos_publicado_com_owner",
        "conteudos",
        "status <> 'publicado' OR "
        "(criado_por_id IS NOT NULL AND publicado_por_id IS NOT NULL "
        "AND publicado_em IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_conteudos_publicado_com_owner", "conteudos", type_="check")
    op.drop_column("conteudos", "publicado_em")
    for coluna in ("publicado_por_id", "atualizado_por_id", "criado_por_id"):
        op.drop_constraint(f"fk_conteudos_{coluna}_users", "conteudos", type_="foreignkey")
        op.drop_column("conteudos", coluna)
