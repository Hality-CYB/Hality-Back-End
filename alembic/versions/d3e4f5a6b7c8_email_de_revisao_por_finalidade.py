"""Permite mais de um e-mail por revisão, um por finalidade.

A reclassificação pelo admin avisa o paciente e o profissional que tinha revisado.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: str | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_email_outbox_review_id", "email_outbox", type_="unique")
    op.create_unique_constraint(
        "uq_email_outbox_review_id_purpose", "email_outbox", ["review_id", "purpose"]
    )


def downgrade() -> None:
    # Volta a um e-mail por revisão: mantém o aviso ao paciente, o mais antigo.
    op.execute("DELETE FROM email_outbox WHERE purpose = 'diagnostic_review_override'")
    op.drop_constraint("uq_email_outbox_review_id_purpose", "email_outbox", type_="unique")
    op.create_unique_constraint("uq_email_outbox_review_id", "email_outbox", ["review_id"])
