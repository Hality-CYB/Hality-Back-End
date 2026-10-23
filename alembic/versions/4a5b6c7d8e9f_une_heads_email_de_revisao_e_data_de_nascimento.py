"""une as heads do e-mail de revisão e da data de nascimento do paciente (#172)

A 4e7a9b1c2d3f (e-mail de revisão) e a 2e3f4a5b6c7d (data de nascimento,
seguida da 3f4a5b6c7d8e) partiram de 1d2e3f4a5b6c. Este merge não altera o
schema, só converge as heads, inclusive em bancos que já aplicaram as duas.

Revision ID: 4a5b6c7d8e9f
Revises: 3f4a5b6c7d8e, 4e7a9b1c2d3f
"""

from collections.abc import Sequence

revision: str = "4a5b6c7d8e9f"
down_revision: str | Sequence[str] | None = ("3f4a5b6c7d8e", "4e7a9b1c2d3f")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
