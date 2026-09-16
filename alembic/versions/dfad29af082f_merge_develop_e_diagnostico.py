"""merge develop e diagnostico

Revision ID: dfad29af082f
Revises: 2ab18391a8a0, ad84d5ad16f6
Create Date: 2026-09-16 01:55:37.492101

"""

from collections.abc import Sequence

revision: str = "dfad29af082f"
down_revision: str | None = ("2ab18391a8a0", "ad84d5ad16f6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
