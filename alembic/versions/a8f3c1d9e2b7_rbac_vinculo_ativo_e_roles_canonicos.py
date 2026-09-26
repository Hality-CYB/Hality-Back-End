"""RBAC: vínculo paciente-profissional ativo e roles canônicos em português

Revision ID: a8f3c1d9e2b7
Revises: 33ca6f19704b
Create Date: 2026-09-26

- Adiciona `pacientes_profissionais.ativo` (só vínculo ativo libera acesso clínico)
  e um índice para a checagem de vínculo por (paciente_id, profissional_id).
- Normaliza `users.role` para o valor canônico persistido (`paciente`,
  `profissional`, `admin`) — linhas antigas criadas com o default `patient`.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8f3c1d9e2b7"
down_revision: str | None = "33ca6f19704b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tem_coluna_ativo() -> bool:
    colunas = sa.inspect(op.get_bind()).get_columns("pacientes_profissionais")
    return any(coluna["name"] == "ativo" for coluna in colunas)


def upgrade() -> None:
    # Idempotente: após um downgrade a coluna continua lá (com os dados), então
    # reaplicar a migração não pode tentar criá-la de novo.
    if not _tem_coluna_ativo():
        op.add_column(
            "pacientes_profissionais",
            sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    op.create_index(
        "ix_pacientes_profissionais_paciente_profissional",
        "pacientes_profissionais",
        ["paciente_id", "profissional_id"],
    )

    op.execute(sa.text("UPDATE users SET role = 'paciente' WHERE lower(role) = 'patient'"))
    op.execute(sa.text("UPDATE users SET role = 'profissional' WHERE lower(role) = 'professional'"))


def downgrade() -> None:
    # Rollback sem apagar dados:
    # - `pacientes_profissionais.ativo` é mantida (quais vínculos foram desativados
    #   não pode se perder). O código anterior ignora a coluna e o server_default
    #   cobre os INSERTs dele.
    # - A normalização de `users.role` não é revertida: o valor original em inglês
    #   não é recuperável e a aplicação aceita os dois formatos na leitura.
    op.drop_index(
        "ix_pacientes_profissionais_paciente_profissional",
        table_name="pacientes_profissionais",
    )
