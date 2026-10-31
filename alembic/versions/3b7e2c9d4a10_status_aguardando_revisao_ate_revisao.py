"""status aguardando_revisao até a revisão profissional

O status passa a dizer se o diagnóstico já foi revisado: a IA termina em
`aguardando_revisao` e a revisão do profissional leva a `concluido`. Os
diagnósticos já gravados como `concluido` sem nenhuma revisão voltam para
`aguardando_revisao`.

Revision ID: 3b7e2c9d4a10
Revises: 901dd00eb21a
Create Date: 2026-10-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3b7e2c9d4a10"
down_revision: str | None = "901dd00eb21a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE diagnosticos
            SET status = 'aguardando_revisao'
            WHERE status = 'concluido'
              AND profissional_revisor_id IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM diagnostico_revisoes r WHERE r.diagnostico_id = diagnosticos.id
              )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE diagnosticos
            SET status = 'concluido'
            WHERE status = 'aguardando_revisao'
              AND classificacao_id IS NOT NULL
            """
        )
    )
