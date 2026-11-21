"""Solicitações profissionais e origem de notificações na outbox.

Revision ID: a5b6c7d8e9f0
Revises: e4f5a6b7c8d9
"""

import sqlalchemy as sa

from alembic import op

revision = "a5b6c7d8e9f0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "solicitacoes_profissionais",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("nome", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("telefone", sa.String(20)),
        sa.Column("registro_profissional", sa.String(50), nullable=False),
        sa.Column("especialidade", sa.String(100), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("termos_aceitos_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("decidido_em", sa.DateTime(timezone=True)),
        sa.Column("decidido_por", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("usuario_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.CheckConstraint(
            "status IN ('pendente', 'aprovada', 'recusada')", name="ck_solicitacao_status"
        ),
    )
    op.create_index(
        "ix_solicitacoes_profissionais_status", "solicitacoes_profissionais", ["status"]
    )
    op.add_column("email_outbox", sa.Column("solicitacao_id", sa.Uuid(), nullable=True))
    op.drop_constraint("ck_email_outbox_one_source", "email_outbox", type_="check")
    op.create_check_constraint(
        "ck_email_outbox_one_source",
        "email_outbox",
        "(CASE WHEN action_id IS NOT NULL THEN 1 ELSE 0 END + "
        "CASE WHEN review_id IS NOT NULL THEN 1 ELSE 0 END + "
        "CASE WHEN solicitacao_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )


def downgrade():
    # Notificações de recusa não têm representação no esquema anterior.
    op.execute("DELETE FROM email_outbox WHERE solicitacao_id IS NOT NULL")
    op.drop_constraint("ck_email_outbox_one_source", "email_outbox", type_="check")
    op.drop_column("email_outbox", "solicitacao_id")
    op.create_check_constraint(
        "ck_email_outbox_one_source",
        "email_outbox",
        "(action_id IS NOT NULL) != (review_id IS NOT NULL)",
    )
    op.drop_index("ix_solicitacoes_profissionais_status", "solicitacoes_profissionais")
    op.drop_table("solicitacoes_profissionais")
