"""cria tabela consentimento_eventos

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
"""

from collections.abc import Sequence

import fastapi_users_db_sqlalchemy
import sqlalchemy as sa

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consentimento_eventos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("titular_id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=False),
        sa.Column("finalidade", sa.String(length=30), nullable=False),
        sa.Column("versao", sa.String(length=20), nullable=False),
        sa.Column("aceito", sa.Boolean(), nullable=False),
        sa.Column("origem", sa.String(length=30), nullable=False),
        sa.Column("ator_id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=True),
        sa.Column("ator_papel", sa.String(length=20), nullable=True),
        sa.Column("referencia_coleta", sa.String(length=128), nullable=True),
        sa.Column(
            "registrado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "finalidade IN ('health_data', 'image_training')",
            name="ck_consentimento_eventos_finalidade",
        ),
        sa.ForeignKeyConstraint(["titular_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ator_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_consentimento_eventos_titular_finalidade",
        "consentimento_eventos",
        ["titular_id", "finalidade", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_consentimento_eventos_titular_finalidade", table_name="consentimento_eventos")
    op.drop_table("consentimento_eventos")
