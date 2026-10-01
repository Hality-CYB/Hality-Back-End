from datetime import UTC, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentProfessionalDep, DbSession
from app.schemas.profissionais import ResumoProfissionalResponse
from app.services import profissional_service

router = APIRouter(prefix="/profissional", tags=["profissional"])

# falei com o Thiago e ele falou que 30 dias ta bom por enquanto, dps o time
# ainda vai decidir o melhor espacamento de dias (DEC-05 na issue)
PERIODO_PADRAO_DIAS = 30


@router.get("/resumo", response_model=ResumoProfissionalResponse)
async def obter_resumo(
    profissional: CurrentProfessionalDep,
    db: DbSession,
    inicio: Annotated[datetime | None, Query()] = None,
    fim: Annotated[datetime | None, Query()] = None,
    timezone: Annotated[str, Query()] = "UTC",
) -> ResumoProfissionalResponse:
    try:
        fuso = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="timezone invalido",
        ) from exc

    # Data sem fuso é interpretada no `timezone` informado; sem isso, comparar
    # com o `fim` padrão (com fuso) levanta TypeError e a rota responde 500.
    if inicio is not None and inicio.tzinfo is None:
        inicio = inicio.replace(tzinfo=fuso)
    if fim is not None and fim.tzinfo is None:
        fim = fim.replace(tzinfo=fuso)

    fim_efetivo = fim or datetime.now(UTC)
    inicio_efetivo = inicio or (fim_efetivo - timedelta(days=PERIODO_PADRAO_DIAS))

    try:
        return await profissional_service.montar_resumo(
            db=db,
            profissional_id=profissional.id,
            inicio=inicio_efetivo,
            fim=fim_efetivo,
            timezone=timezone,
        )

    except profissional_service.PeriodoInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="periodo invalido",
        ) from exc
