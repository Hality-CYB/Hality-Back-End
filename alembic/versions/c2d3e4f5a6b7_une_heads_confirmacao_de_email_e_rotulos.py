"""une as heads da confirmação de e-mail e dos rótulos do dataset

A 5b6c7d8e9f0a (confirmação de e-mail) e a b1c2d3e4f5a6 (rótulos do
dataset) partiram de 4a5b6c7d8e9f. Este merge não altera o schema, só
converge as heads, inclusive em bancos que já aplicaram as duas.

Revision ID: c2d3e4f5a6b7
Revises: 5b6c7d8e9f0a, b1c2d3e4f5a6
"""

from collections.abc import Sequence

revision: str = "c2d3e4f5a6b7"
down_revision: str | Sequence[str] | None = ("5b6c7d8e9f0a", "b1c2d3e4f5a6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
