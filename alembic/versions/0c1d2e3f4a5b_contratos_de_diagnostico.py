"""contratos de estado, erro, rastreabilidade e persistência do diagnóstico (DELTA-12)

Revision ID: 0c1d2e3f4a5b
Revises: 9b0c1d2e3f4a
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0c1d2e3f4a5b"
down_revision: str | None = "9b0c1d2e3f4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUS_VALIDOS = ("processando", "aguardando_revisao", "concluido", "falha")

VERSAO_FALLBACK = "2026-08-v1"
# Data antiga para o fallback não virar a versão vigente (a de `criado_em` mais recente).
CRIADO_EM_FALLBACK = "2026-08-01T00:00:00+00:00"

# Cópia congelada de `_QUESTIONARIO_FALLBACK`: migrations não importam código da aplicação.
PERGUNTAS_FALLBACK = [
    {
        "id": "mau_halito_ao_acordar",
        "enunciado": "Você sente mau hálito ao acordar?",
        "tipo": "boolean",
        "obrigatoria": True,
        "opcoes": None,
        "escala_min": None,
        "escala_max": None,
        "escala_label_min": None,
        "escala_label_max": None,
    },
    {
        "id": "frequencia_escovacao",
        "enunciado": "Com que frequência você escova os dentes?",
        "tipo": "single_choice",
        "obrigatoria": True,
        "opcoes": ["1x ao dia", "2x ao dia", "3x ou mais"],
        "escala_min": None,
        "escala_max": None,
        "escala_label_min": None,
        "escala_label_max": None,
    },
    {
        "id": "sintomas_adicionais",
        "enunciado": "Descreva sintomas adicionais, se houver.",
        "tipo": "text",
        "obrigatoria": False,
        "opcoes": None,
        "escala_min": None,
        "escala_max": None,
        "escala_label_min": None,
        "escala_label_max": None,
    },
    {
        "id": "avaliacao_propria_halito",
        "enunciado": "Como você avalia o cheiro da sua respiração?",
        "tipo": "scale",
        "obrigatoria": True,
        "opcoes": None,
        "escala_min": 1,
        "escala_max": 5,
        "escala_label_min": "Ruim",
        "escala_label_max": "Excelente",
    },
]


def _exigir_vazio(sql: str, mensagem: str) -> None:
    if op.get_bind().execute(sa.text(sql)).first() is not None:
        raise RuntimeError(mensagem)


def upgrade() -> None:
    lista_status = ", ".join(f"'{status}'" for status in STATUS_VALIDOS)
    _exigir_vazio(
        f"SELECT 1 FROM diagnosticos WHERE status NOT IN ({lista_status}) LIMIT 1",
        "Há diagnósticos com status fora do contrato; corrija antes de migrar.",
    )
    _exigir_vazio(
        "SELECT 1 FROM imagens GROUP BY diagnostico_id, ordem HAVING count(*) > 1 LIMIT 1",
        "Há imagens com `ordem` repetida no mesmo diagnóstico; corrija antes de migrar.",
    )

    op.add_column("diagnosticos", sa.Column("origem_resultado", sa.String(20), nullable=True))
    op.add_column("diagnosticos", sa.Column("modelo_provider", sa.String(50), nullable=True))
    op.add_column("diagnosticos", sa.Column("modelo_versao", sa.String(50), nullable=True))
    op.add_column("diagnosticos", sa.Column("erro_codigo", sa.String(50), nullable=True))

    op.execute("UPDATE diagnosticos SET origem_resultado = 'legado' WHERE status <> 'processando'")
    op.execute("UPDATE diagnosticos SET erro_codigo = 'legado_sem_codigo' WHERE status = 'falha'")

    op.create_check_constraint(
        "ck_diagnosticos_status", "diagnosticos", f"status IN ({lista_status})"
    )
    op.create_check_constraint(
        "ck_diagnosticos_origem_resultado",
        "diagnosticos",
        "origem_resultado IN ('legado', 'mock', 'modelo')",
    )
    op.create_check_constraint(
        "ck_diagnosticos_modelo_somente_inferencia",
        "diagnosticos",
        "origem_resultado IS NOT DISTINCT FROM 'modelo' "
        "OR (modelo_provider IS NULL AND modelo_versao IS NULL)",
    )

    op.drop_constraint("diagnosticos_anamnese_id_fkey", "diagnosticos", type_="foreignkey")
    op.create_foreign_key(
        "diagnosticos_anamnese_id_fkey", "diagnosticos", "anamneses", ["anamnese_id"], ["id"]
    )

    op.add_column("imagens", sa.Column("sha256", sa.String(64), nullable=True))
    op.add_column("imagens", sa.Column("content_type", sa.String(30), nullable=True))
    op.add_column("imagens", sa.Column("tamanho_bytes", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_imagens_tamanho_positivo", "imagens", "tamanho_bytes IS NULL OR tamanho_bytes > 0"
    )
    op.create_unique_constraint(
        "uq_imagens_diagnostico_ordem", "imagens", ["diagnostico_id", "ordem"]
    )
    # Coberto pela UNIQUE acima (`diagnostico_id` é a coluna líder).
    op.drop_index("ix_imagens_diagnostico_id", table_name="imagens")

    op.execute(
        sa.text(
            "INSERT INTO questionarios (versao, perguntas, criado_em) "
            "VALUES (:versao, CAST(:perguntas AS JSONB), CAST(:criado_em AS TIMESTAMPTZ)) "
            "ON CONFLICT (versao) DO NOTHING"
        ).bindparams(
            versao=VERSAO_FALLBACK,
            perguntas=json.dumps(PERGUNTAS_FALLBACK, ensure_ascii=False),
            criado_em=CRIADO_EM_FALLBACK,
        )
    )


def downgrade() -> None:
    # A linha do fallback fica: anamneses podem referenciá-la.
    op.create_index("ix_imagens_diagnostico_id", "imagens", ["diagnostico_id"])
    op.drop_constraint("uq_imagens_diagnostico_ordem", "imagens", type_="unique")
    op.drop_constraint("ck_imagens_tamanho_positivo", "imagens", type_="check")
    op.drop_column("imagens", "tamanho_bytes")
    op.drop_column("imagens", "content_type")
    op.drop_column("imagens", "sha256")

    op.drop_constraint("diagnosticos_anamnese_id_fkey", "diagnosticos", type_="foreignkey")
    op.create_foreign_key(
        "diagnosticos_anamnese_id_fkey",
        "diagnosticos",
        "anamneses",
        ["anamnese_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("ck_diagnosticos_modelo_somente_inferencia", "diagnosticos", type_="check")
    op.drop_constraint("ck_diagnosticos_origem_resultado", "diagnosticos", type_="check")
    op.drop_constraint("ck_diagnosticos_status", "diagnosticos", type_="check")
    op.drop_column("diagnosticos", "erro_codigo")
    op.drop_column("diagnosticos", "modelo_versao")
    op.drop_column("diagnosticos", "modelo_provider")
    op.drop_column("diagnosticos", "origem_resultado")
