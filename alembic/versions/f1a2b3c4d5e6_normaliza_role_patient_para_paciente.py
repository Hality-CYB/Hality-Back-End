"""normaliza role patient para paciente

Revision ID: f1a2b3c4d5e6
Revises: 198bcce46c43
Create Date: 2026-09-30 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "198bcce46c43"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE users SET role = 'paciente' WHERE role = 'patient'")


def downgrade() -> None:
    # Irreversível: depois do upgrade não dá para distinguir quem era `patient`.
    pass
