"""Permite notificações de revisão na outbox transacional.

Revision ID: 4e7a9b1c2d3f
Revises: 1d2e3f4a5b6c
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4e7a9b1c2d3f"
down_revision: str | None = "1d2e3f4a5b6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("email_outbox", "action_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("email_outbox", sa.Column("review_id", sa.Integer(), nullable=True))
    op.create_unique_constraint("uq_email_outbox_review_id", "email_outbox", ["review_id"])
    op.create_check_constraint(
        "ck_email_outbox_one_source",
        "email_outbox",
        "(action_id IS NOT NULL) != (review_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_email_outbox_one_source", "email_outbox", type_="check")
    op.drop_constraint("uq_email_outbox_review_id", "email_outbox", type_="unique")
    op.drop_column("email_outbox", "review_id")
    op.alter_column("email_outbox", "action_id", existing_type=sa.Uuid(), nullable=False)
