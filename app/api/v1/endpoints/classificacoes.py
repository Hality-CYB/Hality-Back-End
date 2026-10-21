"""Classificações de diagnóstico (tabela de referência).

O id de cada classificação muda de banco para banco (vem da sequência), então o
cliente precisa desta lista para traduzir `classificacao_ids` em nível, por
exemplo no formulário de conteúdos do admin.
"""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.db import classificacao_queries
from app.schemas.classificacoes_diagnostico import ClassificacaoDiagnosticoDetail

router = APIRouter(prefix="/classificacoes", tags=["classificacoes"])


@router.get("", response_model=list[ClassificacaoDiagnosticoDetail])
async def listar_classificacoes(
    _usuario: CurrentUser,
    db: DbSession,
) -> list[ClassificacaoDiagnosticoDetail]:
    """As classificações em ordem de nível (1 a 3)."""
    classificacoes = await classificacao_queries.listar(db)

    return [ClassificacaoDiagnosticoDetail.model_validate(c) for c in classificacoes]
