"""estado do vinculo paciente-profissional (ativo/encerrado_em + unicidade)

Revision ID: 198bcce46c43
Revises: 33ca6f19704b
Create Date: 2026-09-23 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "198bcce46c43"
down_revision: str | None = "33ca6f19704b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pacientes_profissionais",
        sa.Column(
            "ativo",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.add_column(
        "pacientes_profissionais",
        sa.Column("encerrado_em", sa.DateTime(timezone=True), nullable=True),
    )
    # Impede dois vínculos ativos para o mesmo par paciente/profissional, mas
    # permite revincular depois de uma desvinculação (índice só cobre ativo=true).
    op.create_index(
        "ix_pacientes_profissionais_par_ativo",
        "pacientes_profissionais",
        ["paciente_id", "profissional_id"],
        unique=True,
        postgresql_where=sa.text("ativo"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pacientes_profissionais_par_ativo",
        table_name="pacientes_profissionais",
        postgresql_where=sa.text("ativo"),
    )
    op.drop_column("pacientes_profissionais", "encerrado_em")
    op.drop_column("pacientes_profissionais", "ativo")
