"""cria rate limit persistente para ações de identidade

Revision ID: 8a9b0c1d2e3f
Revises: 7f8e9a0b1c2d
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8a9b0c1d2e3f"
down_revision: str | None = "7f8e9a0b1c2d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_rate_limits",
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key_hash"),
    )


def downgrade() -> None:
    op.drop_table("identity_rate_limits")
