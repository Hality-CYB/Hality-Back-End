"""questionário sem a pergunta de idade

A idade passa a vir da data de nascimento do cadastro. Versões publicadas são
imutáveis (cada anamnese referencia a sua), então esta migration publica a
versão 2026-10-v1: a vigente 2026-09-v1 sem a pergunta `idade`. Em banco que
ainda não tem a 2026-09-v1 (ex.: antes do seed), não faz nada; o seed já cria
as duas versões.

Revision ID: 3f4a5b6c7d8e
Revises: 2e3f4a5b6c7d
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3f4a5b6c7d8e"
down_revision: str | Sequence[str] | None = "2e3f4a5b6c7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO questionarios (versao, perguntas, criado_em)
        SELECT
            '2026-10-v1',
            jsonb_path_query_array(perguntas, '$[*] ? (@.id != "idade")'),
            now()
        FROM questionarios
        WHERE versao = '2026-09-v1'
        ON CONFLICT (versao) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM questionarios WHERE versao = '2026-10-v1'")
