"""une as heads do login Google (#162) e da DELTA-12 (#164)

As duas migrations partiram de 9b0c1d2e3f4a. Este merge não altera o schema,
só converge as heads, inclusive em bancos que já aplicaram as duas.

Revision ID: 1d2e3f4a5b6c
Revises: f2b3c4d5e6a7, 0c1d2e3f4a5b
"""

from collections.abc import Sequence

revision: str = "1d2e3f4a5b6c"
down_revision: str | Sequence[str] | None = ("f2b3c4d5e6a7", "0c1d2e3f4a5b")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
