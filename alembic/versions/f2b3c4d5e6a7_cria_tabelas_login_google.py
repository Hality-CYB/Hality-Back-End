"""cria tabelas de identidade externa e fluxo OAuth (login Google)

Revision ID: f2b3c4d5e6a7
Revises: d6d3ff40f0bc
"""

from collections.abc import Sequence

import fastapi_users_db_sqlalchemy
import sqlalchemy as sa

from alembic import op

revision: str = "f2b3c4d5e6a7"
down_revision: str | None = "d6d3ff40f0bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identidades_externas",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ultimo_login_em", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "subject", name="uq_identidades_externas_provider_subject"),
        sa.UniqueConstraint("user_id", "provider", name="uq_identidades_externas_user_provider"),
    )

    op.create_table(
        "oauth_fluxos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("codigo_hash", sa.String(length=64), nullable=True),
        sa.Column("codigo_expira_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("nome", sa.String(length=255), nullable=True),
        sa.Column("user_id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=True),
        sa.Column("motivo_falha", sa.String(length=50), nullable=True),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash"),
        sa.UniqueConstraint("codigo_hash"),
    )
    op.create_index("ix_oauth_fluxos_criado_em", "oauth_fluxos", ["criado_em"])


def downgrade() -> None:
    op.drop_index("ix_oauth_fluxos_criado_em", table_name="oauth_fluxos")
    op.drop_table("oauth_fluxos")
    op.drop_table("identidades_externas")
