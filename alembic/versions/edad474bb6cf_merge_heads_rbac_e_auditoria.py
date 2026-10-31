"""merge heads rbac e auditoria

Revision ID: edad474bb6cf
Revises: a8f3c1d9e2b7, a8f3c2d91b47
Create Date: 2026-10-01 11:33:11.216033

Migration de merge, sem alteração de schema. A a8f3c1d9e2b7 (#92, RBAC) e a
a8f3c2d91b47 (#94, auditoria de acessos) foram criadas em paralelo a partir da
198bcce46c43, o que deixou o histórico com dois heads e quebrou
`alembic upgrade head`. Esta revisão une os dois ramos.
"""

from collections.abc import Sequence

revision: str = "edad474bb6cf"
down_revision: str | Sequence[str] | None = ("a8f3c1d9e2b7", "a8f3c2d91b47")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
