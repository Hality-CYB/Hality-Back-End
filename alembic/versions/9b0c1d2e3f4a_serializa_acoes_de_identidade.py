"""serializa ações de identidade ativas por usuário e finalidade

Revision ID: 9b0c1d2e3f4a
Revises: 8a9b0c1d2e3f
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9b0c1d2e3f4a"
down_revision: str | None = "8a9b0c1d2e3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_identity_actions_active_user_purpose",
        "identity_actions",
        ["user_id", "purpose"],
        unique=True,
        postgresql_where="used_at IS NULL AND revoked_at IS NULL",
        sqlite_where="used_at IS NULL AND revoked_at IS NULL",
    )


def downgrade() -> None:
    op.drop_index("uq_identity_actions_active_user_purpose", table_name="identity_actions")
