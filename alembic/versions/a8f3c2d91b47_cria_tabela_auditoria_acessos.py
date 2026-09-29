"""cria tabela auditoria_acessos

Revision ID: a8f3c2d91b47
Revises: 33ca6f19704b
Create Date: 2026-09-28 10:00:00.000000

"""

from collections.abc import Sequence

import fastapi_users_db_sqlalchemy
import sqlalchemy as sa

from alembic import op

revision: str = "a8f3c2d91b47"
down_revision: str | None = "33ca6f19704b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auditoria_acessos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ator_id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=True),
        sa.Column("acao", sa.String(length=50), nullable=False),
        sa.Column("recurso_tipo", sa.String(length=50), nullable=False),
        sa.Column("recurso_id", sa.String(length=50), nullable=False),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["ator_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auditoria_acessos_ator_id", "auditoria_acessos", ["ator_id"])
    op.create_index(
        "ix_auditoria_acessos_recurso", "auditoria_acessos", ["recurso_tipo", "recurso_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_auditoria_acessos_recurso", table_name="auditoria_acessos")
    op.drop_index("ix_auditoria_acessos_ator_id", table_name="auditoria_acessos")
    op.drop_table("auditoria_acessos")
