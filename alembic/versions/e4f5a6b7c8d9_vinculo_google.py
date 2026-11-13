"""Registra a finalidade do fluxo OAuth e o e-mail da identidade."""

import sqlalchemy as sa

from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("identidades_externas", sa.Column("email", sa.String(320), nullable=True))
    # Antes desta migração, o único vínculo Google era criado junto com a conta,
    # usando o e-mail verificado fornecido pelo Google.
    op.execute(
        "UPDATE identidades_externas SET email = users.email FROM users "
        "WHERE identidades_externas.user_id = users.id AND identidades_externas.provider = 'google'"
    )
    op.add_column("oauth_fluxos", sa.Column("vincular_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_oauth_vincular_user",
        "oauth_fluxos",
        "users",
        ["vincular_user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_oauth_vincular_user", "oauth_fluxos", type_="foreignkey")
    op.drop_column("oauth_fluxos", "vincular_user_id")
    op.drop_column("identidades_externas", "email")
