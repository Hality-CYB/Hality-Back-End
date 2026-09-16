"""adiciona metadados do fluxo de diagnostico

Revision ID: <gerado pelo alembic>
Revises: <gerado pelo alembic>
Create Date: <gerado pelo alembic>
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ad84d5ad16f6"
down_revision: str | None = "594b04654498"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "diagnosticos",
        sa.Column(
            "score",
            sa.Float(),
            nullable=True,
        ),
    )

    op.add_column(
        "diagnosticos",
        sa.Column(
            "provider",
            sa.String(length=100),
            nullable=True,
        ),
    )

    op.add_column(
        "diagnosticos",
        sa.Column(
            "model_version",
            sa.String(length=100),
            nullable=True,
        ),
    )

    op.add_column(
        "diagnosticos",
        sa.Column(
            "data_envio",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "diagnosticos",
        sa.Column(
            "data_processamento",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_unique_constraint(
        "uq_imagens_diagnostico_id",
        "imagens",
        ["diagnostico_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_imagens_diagnostico_id",
        "imagens",
        type_="unique",
    )

    op.drop_column(
        "diagnosticos",
        "data_processamento",
    )

    op.drop_column(
        "diagnosticos",
        "data_envio",
    )

    op.drop_column(
        "diagnosticos",
        "model_version",
    )

    op.drop_column(
        "diagnosticos",
        "provider",
    )

    op.drop_column(
        "diagnosticos",
        "score",
    )
