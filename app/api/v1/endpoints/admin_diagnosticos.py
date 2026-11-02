"""Consulta administrativa de diagnósticos (US-120 / DELTA-08).

As rotas deste módulo são somente leitura; a mutation de rótulo Hality fica em
`admin_rotulos_dataset` e não há rota de exportação neste escopo. O guard de
admin fica no router para valer automaticamente para qualquer rota adicionada
aqui no futuro.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentAdminDep, DbSession, require_admin
from app.schemas.admin_diagnostico import (
    AdminDiagnosticoDetalhe,
    AdminDiagnosticoListResponse,
)
from app.services import diagnostico_service

router = APIRouter(
    prefix="/admin/diagnosticos",
    tags=["admin-diagnosticos"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=AdminDiagnosticoListResponse)
async def listar_diagnosticos_admin(
    db: DbSession,
    paciente_id: Annotated[
        uuid.UUID | None, Query(description="filtra pelo paciente; UUID")
    ] = None,
    classificacao: Annotated[
        str | None, Query(description="código da classificação automática")
    ] = None,
    sem_classificacao: Annotated[
        bool, Query(description="somente diagnósticos sem classificação automática")
    ] = False,
    status_diagnostico: Annotated[
        str | None,
        Query(
            alias="status",
            description=("status: processando, falha, aguardando_revisao ou concluido"),
        ),
    ] = None,
    data_inicio: Annotated[
        str | None,
        Query(
            description=(
                "data inicial inclusiva; YYYY-MM-DD ou ISO 8601 completo (com timezone opcional)"
            )
        ),
    ] = None,
    data_fim: Annotated[
        str | None,
        Query(
            description=(
                "data final inclusiva; YYYY-MM-DD ou ISO 8601 completo (com timezone opcional)"
            )
        ),
    ] = None,
    pagina: Annotated[
        int,
        Query(description="página iniciando em 1; valores menores retornam 400"),
    ] = 1,
    limite: Annotated[
        int,
        Query(description="itens por página; de 1 a 50; fora da faixa retorna 400"),
    ] = 20,
    ordem: Annotated[
        str, Query(description="ordenação: data_desc ou data_asc; desempate por id")
    ] = "data_desc",
) -> AdminDiagnosticoListResponse:
    """Lista a fila admin com filtros combináveis e paginação estável.

    ``paciente_id``, ``classificacao`` e ``sem_classificacao`` filtram o
    conteúdo; ``status`` e ``data_inicio``/``data_fim`` filtram processamento
    e período inclusivo. ``pagina`` começa em 1, ``limite`` vai de 1 a 50 e
    ``ordem`` aceita ``data_asc`` ou ``data_desc`` (com desempate por id).
    ``classificacao`` e ``sem_classificacao`` são mutuamente exclusivos.
    Erros semânticos de filtro retornam 400, pois são validados pelo service
    para preservar o contrato existente; somente tipos malformados no parsing
    do FastAPI, como um UUID inválido, retornam 422.
    """
    try:
        return await diagnostico_service.listar_diagnosticos_admin(
            db=db,
            paciente_id=paciente_id,
            classificacao=classificacao,
            sem_classificacao=sem_classificacao,
            status=status_diagnostico,
            data_inicio=data_inicio,
            data_fim=data_fim,
            pagina=pagina,
            limite=limite,
            ordem=ordem,
        )

    except diagnostico_service.DiagnosticoFiltroInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.motivo,
        ) from exc


@router.get("/{diagnostico_id}", response_model=AdminDiagnosticoDetalhe)
async def obter_diagnostico_admin(
    diagnostico_id: int,
    admin: CurrentAdminDep,
    db: DbSession,
) -> AdminDiagnosticoDetalhe:
    try:
        return await diagnostico_service.obter_diagnostico_admin(
            db=db,
            admin_id=admin.id,
            diagnostico_id=diagnostico_id,
        )

    except diagnostico_service.DiagnosticoNaoEncontradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="diagnóstico não encontrado",
        ) from exc
