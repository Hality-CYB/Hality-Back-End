import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    CurrentAdminDep,
    CurrentAdminMutationDep,
    DbSession,
    LimiteQuery,
    PaginaQuery,
)
from app.schemas.solicitacao_profissional import (
    DecisaoSolicitacao,
    SolicitacaoProfissionalCreate,
    SolicitacaoProfissionalRead,
    SolicitacoesProfissionaisRead,
)
from app.services import solicitacao_profissional_service as service
from app.services.identity_token_service import (
    PROFESSIONAL_REQUEST_RATE_WINDOW_SECONDS,
    consume_rate_limit,
)

router = APIRouter(tags=["solicitacoes-profissionais"])


@router.post("/auth/profissionais/solicitacoes", status_code=202)
async def solicitar(dados: SolicitacaoProfissionalCreate, request: Request, db: DbSession):
    if await consume_rate_limit(
        db,
        f"solicitacao_profissional:{request.client.host}",
        limit=6,
        window_seconds=PROFESSIONAL_REQUEST_RATE_WINDOW_SECONDS,
    ):
        raise HTTPException(429, "Muitas solicitações. Aguarde antes de tentar novamente.")
    try:
        await service.solicitar(db, dados)
    except (service.ConflitoSolicitacaoError, IntegrityError) as exc:
        await db.rollback()
        raise HTTPException(
            409, "Este e-mail já possui conta ou solicitação. Entre em contato com a Hality."
        ) from exc
    return {
        "message": (
            "Solicitação enviada. O acesso depende de aprovação administrativa. "
            "Você receberá a decisão por e-mail."
        )
    }


@router.get("/admin/solicitacoes-profissionais", response_model=SolicitacoesProfissionaisRead)
async def listar(
    admin: CurrentAdminDep,
    db: DbSession,
    status: Literal["pendente", "aprovada", "recusada"] = "pendente",
    pagina: PaginaQuery = 1,
    limite: LimiteQuery = 20,
):
    return await service.listar(db, status, pagina, limite)


@router.post(
    "/admin/solicitacoes-profissionais/{id}/decisao", response_model=SolicitacaoProfissionalRead
)
async def decidir(
    id: uuid.UUID, dados: DecisaoSolicitacao, admin: CurrentAdminMutationDep, db: DbSession
):
    try:
        return await service.decidir(db, id, dados.decisao, admin)
    except service.SolicitacaoNaoEncontradaError as exc:
        raise HTTPException(404, "Solicitação não encontrada.") from exc
    except service.ConflitoSolicitacaoError as exc:
        raise HTTPException(
            409, "Solicitação já decidida ou e-mail já cadastrado. Atualize a lista."
        ) from exc
