"""migra users para uuid do fastapi-users

Revision ID: b0c76688b722
Revises: b4c99c48b0f2
Create Date: 2026-09-11 21:02:26.008501

"""

from collections.abc import Sequence

import fastapi_users_db_sqlalchemy
import sqlalchemy as sa

from alembic import op

revision: str = "b0c76688b722"
down_revision: str | None = "b4c99c48b0f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Tabelas esvaziadas na ordem reversa das foreign keys.
_TABELAS_DEPENDENTES = (
    "anamneses",
    "imagens",
    "pacientes_profissionais",
    "diagnosticos",
    "profissionais",
    "users",
)

# (tabela, coluna, nullable) — colunas que referenciam users.id / profissionais.usuario_id.
_COLUNAS_FK = (
    ("anamneses", "paciente_id", False),
    ("diagnosticos", "paciente_id", False),
    ("diagnosticos", "profissional_revisor_id", True),
    ("pacientes_profissionais", "paciente_id", False),
    ("pacientes_profissionais", "profissional_id", False),
)


def upgrade() -> None:
    for tabela in _TABELAS_DEPENDENTES:
        op.execute(f"DELETE FROM {tabela}")

    # 1. soltar as constraints que travam a troca de tipo
    op.drop_constraint("anamneses_paciente_id_fkey", "anamneses", type_="foreignkey")
    op.drop_constraint("diagnosticos_paciente_id_fkey", "diagnosticos", type_="foreignkey")
    op.drop_constraint(
        "diagnosticos_profissional_revisor_id_fkey", "diagnosticos", type_="foreignkey"
    )
    op.drop_constraint(
        "pacientes_profissionais_paciente_id_fkey", "pacientes_profissionais", type_="foreignkey"
    )
    op.drop_constraint(
        "pacientes_profissionais_profissional_id_fkey",
        "pacientes_profissionais",
        type_="foreignkey",
    )
    op.drop_constraint("profissionais_usuario_id_fkey", "profissionais", type_="foreignkey")
    op.drop_constraint("profissionais_pkey", "profissionais", type_="primary")
    op.drop_constraint("users_pkey", "users", type_="primary")

    # 2. recriar users.id como UUID (o DROP leva junto a sequence do serial)
    op.drop_column("users", "id")
    op.add_column(
        "users",
        sa.Column(
            "id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.create_primary_key("users_pkey", "users", ["id"])
    # o UUID passa a ser gerado pelo fastapi-users, na aplicacao
    op.alter_column("users", "id", server_default=None)

    # 3. recriar as colunas que apontam para users.id
    op.drop_column("profissionais", "usuario_id")
    op.add_column(
        "profissionais",
        sa.Column("usuario_id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=False),
    )
    op.create_primary_key("profissionais_pkey", "profissionais", ["usuario_id"])

    for tabela, coluna, nullable in _COLUNAS_FK:
        op.drop_column(tabela, coluna)
        op.add_column(
            tabela,
            sa.Column(coluna, fastapi_users_db_sqlalchemy.generics.GUID(), nullable=nullable),
        )

    # 4. refazer as foreign keys
    op.create_foreign_key(
        "anamneses_paciente_id_fkey",
        "anamneses",
        "users",
        ["paciente_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "profissionais_usuario_id_fkey",
        "profissionais",
        "users",
        ["usuario_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "diagnosticos_paciente_id_fkey",
        "diagnosticos",
        "users",
        ["paciente_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "diagnosticos_profissional_revisor_id_fkey",
        "diagnosticos",
        "users",
        ["profissional_revisor_id"],
        ["id"],
    )
    op.create_foreign_key(
        "pacientes_profissionais_paciente_id_fkey",
        "pacientes_profissionais",
        "users",
        ["paciente_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "pacientes_profissionais_profissional_id_fkey",
        "pacientes_profissionais",
        "profissionais",
        ["profissional_id"],
        ["usuario_id"],
        ondelete="CASCADE",
    )

    # 5. demais campos herdados do fastapi-users
    op.add_column(
        "users",
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column(
        "users",
        "email",
        existing_type=sa.VARCHAR(length=255),
        type_=sa.String(length=320),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "hashed_password",
        existing_type=sa.VARCHAR(length=255),
        type_=sa.String(length=1024),
        existing_nullable=False,
    )


def downgrade() -> None:
    for tabela in _TABELAS_DEPENDENTES:
        op.execute(f"DELETE FROM {tabela}")

    op.alter_column(
        "users",
        "hashed_password",
        existing_type=sa.String(length=1024),
        type_=sa.VARCHAR(length=255),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "email",
        existing_type=sa.String(length=320),
        type_=sa.VARCHAR(length=255),
        existing_nullable=False,
    )
    op.drop_column("users", "is_verified")
    op.drop_column("users", "is_superuser")

    op.drop_constraint("anamneses_paciente_id_fkey", "anamneses", type_="foreignkey")
    op.drop_constraint("diagnosticos_paciente_id_fkey", "diagnosticos", type_="foreignkey")
    op.drop_constraint(
        "diagnosticos_profissional_revisor_id_fkey", "diagnosticos", type_="foreignkey"
    )
    op.drop_constraint(
        "pacientes_profissionais_paciente_id_fkey", "pacientes_profissionais", type_="foreignkey"
    )
    op.drop_constraint(
        "pacientes_profissionais_profissional_id_fkey",
        "pacientes_profissionais",
        type_="foreignkey",
    )
    op.drop_constraint("profissionais_usuario_id_fkey", "profissionais", type_="foreignkey")
    op.drop_constraint("profissionais_pkey", "profissionais", type_="primary")
    op.drop_constraint("users_pkey", "users", type_="primary")

    for tabela, coluna, nullable in _COLUNAS_FK:
        op.drop_column(tabela, coluna)
        op.add_column(tabela, sa.Column(coluna, sa.Integer(), nullable=nullable))

    op.drop_column("profissionais", "usuario_id")
    op.add_column("profissionais", sa.Column("usuario_id", sa.Integer(), nullable=False))
    op.create_primary_key("profissionais_pkey", "profissionais", ["usuario_id"])

    op.drop_column("users", "id")
    op.add_column(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    )
    op.execute("CREATE SEQUENCE users_id_seq OWNED BY users.id")
    op.execute("ALTER TABLE users ALTER COLUMN id SET DEFAULT nextval('users_id_seq')")
    op.create_primary_key("users_pkey", "users", ["id"])

    op.create_foreign_key(
        "anamneses_paciente_id_fkey",
        "anamneses",
        "users",
        ["paciente_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "profissionais_usuario_id_fkey",
        "profissionais",
        "users",
        ["usuario_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "diagnosticos_paciente_id_fkey",
        "diagnosticos",
        "users",
        ["paciente_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "diagnosticos_profissional_revisor_id_fkey",
        "diagnosticos",
        "users",
        ["profissional_revisor_id"],
        ["id"],
    )
    op.create_foreign_key(
        "pacientes_profissionais_paciente_id_fkey",
        "pacientes_profissionais",
        "users",
        ["paciente_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "pacientes_profissionais_profissional_id_fkey",
        "pacientes_profissionais",
        "profissionais",
        ["profissional_id"],
        ["usuario_id"],
        ondelete="CASCADE",
    )
