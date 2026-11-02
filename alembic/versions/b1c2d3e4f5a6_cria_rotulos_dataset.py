"""cria histórico append-only de rótulos Hality para dataset

Revision ID: b1c2d3e4f5a6
Revises: 4a5b6c7d8e9f
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "4a5b6c7d8e9f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rotulos_dataset",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("diagnostico_id", sa.Integer(), nullable=False),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("classificacao_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rotulo_anterior_id", sa.Integer(), nullable=True),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version > 0", name="ck_rotulos_dataset_version_positiva"),
        sa.ForeignKeyConstraint(["diagnostico_id"], ["diagnosticos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["classificacao_id"], ["classificacoes_diagnostico.id"]),
        sa.ForeignKeyConstraint(["rotulo_anterior_id"], ["rotulos_dataset.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "diagnostico_id", "version", name="uq_rotulos_dataset_diagnostico_version"
        ),
    )
    op.create_index(
        "ix_rotulos_dataset_diagnostico_version",
        "rotulos_dataset",
        ["diagnostico_id", "version"],
    )


def downgrade() -> None:
    op.drop_index("ix_rotulos_dataset_diagnostico_version", table_name="rotulos_dataset")
    op.drop_table("rotulos_dataset")
