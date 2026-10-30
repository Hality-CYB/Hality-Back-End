from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5b6c7d8e9f0a"
down_revision: str | Sequence[str] | None = "4a5b6c7d8e9f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE users SET is_verified = true WHERE is_active = true"))


def downgrade() -> None:
    pass
