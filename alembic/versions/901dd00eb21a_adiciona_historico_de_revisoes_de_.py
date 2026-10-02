"""adiciona historico de revisoes de diagnostico

Revision ID: 901dd00eb21a
Revises: f1a2b3c4d5e6
Create Date: 2026-10-01 19:44:57.237180
"""

from collections.abc import Sequence

import sqlalchemy as sa
from fastapi_users_db_sqlalchemy.generics import GUID

from alembic import op

revision: str = "901dd00eb21a"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "diagnostico_revisoes",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "diagnostico_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "profissional_id",
            GUID(),
            nullable=False,
        ),
        sa.Column(
            "classificacao_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "observacao",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "versao",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "revisao_anterior_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["classificacao_id"],
            ["classificacoes_diagnostico.id"],
        ),
        sa.ForeignKeyConstraint(
            ["diagnostico_id"],
            ["diagnosticos.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profissional_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["revisao_anterior_id"],
            ["diagnostico_revisoes.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "diagnostico_id",
            "versao",
            name="uq_diagnostico_revisoes_diagnostico_versao",
        ),
    )


def downgrade() -> None:
    op.drop_table("diagnostico_revisoes")
