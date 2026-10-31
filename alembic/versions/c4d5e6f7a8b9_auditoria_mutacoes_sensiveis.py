"""adiciona campos para auditoria de mutacoes sensiveis

Revision ID: c4d5e6f7a8b9
Revises: edad474bb6cf
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "3b7e2c9d4a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("auditoria_acessos", sa.Column("papel", sa.String(length=20), nullable=True))
    op.add_column(
        "auditoria_acessos",
        sa.Column("resultado", sa.String(length=20), server_default="sucesso", nullable=False),
    )
    op.add_column("auditoria_acessos", sa.Column("metadados", sa.JSON(), nullable=True))
    op.add_column(
        "auditoria_acessos", sa.Column("chave_operacao", sa.String(length=100), nullable=True)
    )
    op.create_unique_constraint(
        "uq_auditoria_acessos_chave_operacao", "auditoria_acessos", ["chave_operacao"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_auditoria_acessos_chave_operacao", "auditoria_acessos", type_="unique")
    op.drop_column("auditoria_acessos", "chave_operacao")
    op.drop_column("auditoria_acessos", "metadados")
    op.drop_column("auditoria_acessos", "resultado")
    op.drop_column("auditoria_acessos", "papel")
