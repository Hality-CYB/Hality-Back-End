"""adiciona autoria e publicacao a conteudos

Revision ID: a82d5d4b3f10
Revises: edad474bb6cf
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a82d5d4b3f10"
down_revision: str | None = "edad474bb6cf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for coluna in ("criado_por_id", "atualizado_por_id", "publicado_por_id"):
        op.add_column(
            "conteudos",
            sa.Column(coluna, postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            f"fk_conteudos_{coluna}_users",
            "conteudos",
            "users",
            [coluna],
            ["id"],
        )

    op.add_column("conteudos", sa.Column("publicado_em", sa.DateTime(timezone=True), nullable=True))

    # Conteúdo legado já publicado não tem autoria registrada. Para não sumir do
    # app no deploy, é atribuído ao primeiro admin ativo; sem admin, volta para
    # rascunho até alguém publicar de novo.
    op.execute(
        """
        UPDATE conteudos
        SET criado_por_id = admin.id,
            atualizado_por_id = admin.id,
            publicado_por_id = admin.id,
            publicado_em = now()
        FROM (
            SELECT id FROM users
            WHERE role = 'admin' AND is_active
            ORDER BY created_at, id
            LIMIT 1
        ) AS admin
        WHERE conteudos.status = 'publicado'
        """
    )
    op.execute(
        "UPDATE conteudos SET status = 'rascunho' "
        "WHERE status = 'publicado' AND criado_por_id IS NULL"
    )
    op.create_check_constraint(
        "ck_conteudos_publicado_com_owner",
        "conteudos",
        "status <> 'publicado' OR "
        "(criado_por_id IS NOT NULL AND publicado_por_id IS NOT NULL "
        "AND publicado_em IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_conteudos_publicado_com_owner", "conteudos", type_="check")
    op.drop_column("conteudos", "publicado_em")
    for coluna in ("publicado_por_id", "atualizado_por_id", "criado_por_id"):
        op.drop_constraint(f"fk_conteudos_{coluna}_users", "conteudos", type_="foreignkey")
        op.drop_column("conteudos", coluna)
