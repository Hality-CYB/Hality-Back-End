"""cria ações de identidade e outbox de e-mail

Revision ID: 7f8e9a0b1c2d
Revises: c4d5e6f7a8b9
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7f8e9a0b1c2d"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_identity_actions_user_purpose", "identity_actions", ["user_id", "purpose"])
    op.create_index("ix_identity_actions_expires_at", "identity_actions", ["expires_at"])

    op.create_table(
        "email_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["action_id"], ["identity_actions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_email_outbox_status_available_at",
        "email_outbox",
        ["status", "available_at"],
    )
    op.create_index("ix_email_outbox_correlation_id", "email_outbox", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_email_outbox_correlation_id", table_name="email_outbox")
    op.drop_index("ix_email_outbox_status_available_at", table_name="email_outbox")
    op.drop_table("email_outbox")
    op.drop_index("ix_identity_actions_expires_at", table_name="identity_actions")
    op.drop_index("ix_identity_actions_user_purpose", table_name="identity_actions")
    op.drop_table("identity_actions")
