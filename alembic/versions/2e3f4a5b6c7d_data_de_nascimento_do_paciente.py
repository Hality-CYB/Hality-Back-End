"""data de nascimento do paciente

A coluna fica opcional no banco (profissional e admin não têm), mas é
obrigatória no cadastro de paciente. Usuários que já existem recebem uma data
qualquer (1990-01-01), a pedido do time, para não ficarem sem o dado.

Revision ID: 2e3f4a5b6c7d
Revises: 1d2e3f4a5b6c
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2e3f4a5b6c7d"
down_revision: str | Sequence[str] | None = "1d2e3f4a5b6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("data_nascimento", sa.Date(), nullable=True))
    op.execute("UPDATE users SET data_nascimento = DATE '1990-01-01' WHERE data_nascimento IS NULL")


def downgrade() -> None:
    op.drop_column("users", "data_nascimento")
