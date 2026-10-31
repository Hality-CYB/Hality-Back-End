from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import DbSession, require_admin
from app.schemas.admin_resumo import AdminResumoResponse
from app.services import admin_resumo_service
from app.services.periodo import TimezoneInvalidoError, resolver_periodo

# o require_admin fica no router pra valer pra todas as rotas daqui
router = APIRouter(
    prefix="/admin",
    tags=["admin-resumo"],
    dependencies=[Depends(require_admin)],
)


@router.get("/resumo", response_model=AdminResumoResponse)
async def obter_resumo_admin(
    db: DbSession,
    inicio: Annotated[datetime | None, Query()] = None,
    fim: Annotated[datetime | None, Query()] = None,
    timezone: Annotated[str, Query()] = "UTC",
) -> AdminResumoResponse:
    try:
        inicio_efetivo, fim_efetivo = resolver_periodo(inicio, fim, timezone)
    except TimezoneInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="timezone invalido",
        ) from exc

    try:
        return await admin_resumo_service.montar_resumo(
            db=db,
            inicio=inicio_efetivo,
            fim=fim_efetivo,
            timezone=timezone,
        )

    except admin_resumo_service.PeriodoInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="periodo invalido",
        ) from exc

    except admin_resumo_service.PeriodoMuitoLongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"periodo maior que {admin_resumo_service.LIMITE_PERIODO_DIAS} dias",
        ) from exc
