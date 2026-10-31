"""RBAC: roles canônicos em português

Revision ID: a8f3c1d9e2b7
Revises: 198bcce46c43
Create Date: 2026-09-26

Normaliza `users.role` para o valor canônico persistido (`paciente`,
`profissional`, `admin`) — linhas antigas criadas com o default `patient`.

A coluna `pacientes_profissionais.ativo` e o índice único parcial
`ix_pacientes_profissionais_par_ativo` (que atende a checagem de vínculo ativo
por paciente/profissional) vêm da 198bcce46c43.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8f3c1d9e2b7"
down_revision: str | None = "198bcce46c43"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE users SET role = 'paciente' WHERE lower(role) = 'patient'"))
    op.execute(sa.text("UPDATE users SET role = 'profissional' WHERE lower(role) = 'professional'"))


def downgrade() -> None:
    # Rollback sem apagar dados: a normalização de `users.role` não é revertida —
    # o valor original em inglês não é recuperável e a aplicação aceita os dois
    # formatos na leitura.
    pass
