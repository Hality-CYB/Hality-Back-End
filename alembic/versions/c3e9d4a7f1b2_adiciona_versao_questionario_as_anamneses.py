"""adiciona versao do questionario as anamneses

Revision ID: c3e9d4a7f1b2
Revises: 652cbc54920d
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3e9d4a7f1b2"
down_revision: str | None = "652cbc54920d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "anamneses",
        sa.Column(
            "id_versao_questionario",
            sa.String(length=50),
            nullable=False,
            server_default="2026-08-v1",
        ),
    )


def downgrade() -> None:
    op.drop_column("anamneses", "id_versao_questionario")
