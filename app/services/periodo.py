"""Periodo e timezone usados nos resumos (do profissional e do admin)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# falei com o Thiago e ele falou que 30 dias ta bom por enquanto, dps o time
# ainda vai decidir o melhor espacamento de dias (DEC-05 na issue)
PERIODO_PADRAO_DIAS = 30


class TimezoneInvalidoError(Exception):
    pass


def resolver_periodo(
    inicio: datetime | None,
    fim: datetime | None,
    timezone: str,
    agora: datetime | None = None,
) -> tuple[datetime, datetime]:
    # devolve o inicio e o fim ja com fuso e com os valores padrao
    try:
        fuso = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise TimezoneInvalidoError(timezone) from exc

    # Data sem fuso é interpretada no `timezone` informado; sem isso, comparar
    # com o `fim` padrão (com fuso) levanta TypeError e a rota responde 500.
    if inicio is not None and inicio.tzinfo is None:
        inicio = inicio.replace(tzinfo=fuso)

    if fim is not None and fim.tzinfo is None:
        fim = fim.replace(tzinfo=fuso)

    # sem fim usa o momento de agora, sem inicio usa 30 dias antes do fim
    fim_efetivo = fim or (agora or datetime.now(UTC))

    inicio_efetivo = inicio or (fim_efetivo - timedelta(days=PERIODO_PADRAO_DIAS))

    return inicio_efetivo, fim_efetivo
