"""adiciona executor_id em anamneses e diagnosticos (US-090)

Separa o titular (`paciente_id`) de quem executou a ação (`executor_id`):
o próprio paciente na autoavaliação ou o profissional vinculado no
atendimento. A coluna é nula e sem backfill — registros existentes ficam com
executor nulo (legado) em vez de serem reclassificados.

Revision ID: f1a2b3c4d5e6
Revises: a82d5d4b3f10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "a82d5d4b3f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABELAS = ("anamneses", "diagnosticos")


def upgrade() -> None:
    for tabela in _TABELAS:
        op.add_column(tabela, sa.Column("executor_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"{tabela}_executor_id_fkey",
            tabela,
            "users",
            ["executor_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for tabela in reversed(_TABELAS):
        op.drop_constraint(f"{tabela}_executor_id_fkey", tabela, type_="foreignkey")
        op.drop_column(tabela, "executor_id")
