"""data de nascimento do paciente

A coluna fica opcional no banco (profissional e admin não têm), mas é
obrigatória no cadastro de paciente. Usuários que já existem ficam sem a data:
uma data inventada seria indistinguível de uma real e viraria a única idade do
paciente. O paciente antigo informa a data pelo perfil.

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


def downgrade() -> None:
    op.drop_column("users", "data_nascimento")
