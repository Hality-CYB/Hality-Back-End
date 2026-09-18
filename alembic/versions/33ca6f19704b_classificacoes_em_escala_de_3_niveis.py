"""classificações de diagnóstico em escala de 3 níveis (ordem 1 a 3)"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "33ca6f19704b"
down_revision: str | None = "e7c1d2a3b4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOVAS = [
    (1, "halito_normal", "Hálito Normal"),
    (2, "halitose_intima", "Halitose Íntima"),
    (3, "mau_halito_social", "Mau Hálito Social"),
]

_ANTIGAS = [
    (1, "halitose_leve", "Halitose Leve"),
    (2, "halitose_social", "Halitose Social"),
    (3, "halitose_severa", "Halitose Severa"),
]

_FORA_DA_ESCALA = "SELECT id FROM classificacoes_diagnostico WHERE ordem NOT BETWEEN 1 AND 3"
_NIVEL_1 = "(SELECT id FROM classificacoes_diagnostico WHERE ordem = 1)"


def _upsert_por_ordem(linhas: list[tuple[int, str, str]]) -> None:
    for ordem, codigo, nome in linhas:
        params = {"ordem": ordem, "codigo": codigo, "nome": nome}
        op.execute(
            sa.text(
                "UPDATE classificacoes_diagnostico "
                "SET codigo = :codigo, nome_exibicao = :nome WHERE ordem = :ordem"
            ).bindparams(**params)
        )
        op.execute(
            sa.text(
                "INSERT INTO classificacoes_diagnostico (codigo, nome_exibicao, ordem) "
                "SELECT :codigo, :nome, :ordem WHERE NOT EXISTS "
                "(SELECT 1 FROM classificacoes_diagnostico WHERE ordem = :ordem)"
            ).bindparams(**params)
        )


def upgrade() -> None:
    _upsert_por_ordem(_NOVAS)

    op.execute(
        sa.text(
            f"UPDATE diagnosticos SET classificacao_id = {_NIVEL_1} "
            f"WHERE classificacao_id IN ({_FORA_DA_ESCALA})"
        )
    )
    op.execute(
        sa.text(
            "UPDATE conteudos SET classificacao_ids = ARRAY("
            f"SELECT DISTINCT CASE WHEN x IN ({_FORA_DA_ESCALA}) THEN {_NIVEL_1} ELSE x END "
            "FROM unnest(classificacao_ids) AS x ORDER BY 1) "
            f"WHERE classificacao_ids && ARRAY({_FORA_DA_ESCALA})"
        )
    )
    op.execute(sa.text(f"DELETE FROM classificacoes_diagnostico WHERE id IN ({_FORA_DA_ESCALA})"))

    op.create_unique_constraint(
        "uq_classificacoes_diagnostico_ordem", "classificacoes_diagnostico", ["ordem"]
    )
    op.create_check_constraint(
        "ck_classificacoes_diagnostico_ordem",
        "classificacoes_diagnostico",
        "ordem BETWEEN 1 AND 3",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_classificacoes_diagnostico_ordem", "classificacoes_diagnostico", type_="check"
    )
    op.drop_constraint(
        "uq_classificacoes_diagnostico_ordem", "classificacoes_diagnostico", type_="unique"
    )
    _upsert_por_ordem(_ANTIGAS)
    _upsert_por_ordem([(0, "saudavel", "Saudável")])
