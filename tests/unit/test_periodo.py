from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.periodo import (
    PERIODO_PADRAO_DIAS,
    TimezoneInvalidoError,
    resolver_periodo,
)

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def test_periodo_padrao_continua_30_dias():
    # o resumo do profissional usava esse valor antes de ir pro arquivo novo
    assert PERIODO_PADRAO_DIAS == 30


def test_sem_datas_usa_agora_e_os_ultimos_30_dias():
    inicio, fim = resolver_periodo(None, None, "UTC", agora=AGORA)

    assert fim == AGORA
    assert inicio == AGORA - timedelta(days=30)


def test_so_o_inicio_informado_mantem_o_fim_em_agora():
    inicio, fim = resolver_periodo(datetime(2026, 9, 1, tzinfo=UTC), None, "UTC", agora=AGORA)

    assert inicio == datetime(2026, 9, 1, tzinfo=UTC)
    assert fim == AGORA


def test_data_sem_fuso_usa_o_timezone_informado():
    inicio, fim = resolver_periodo(
        datetime(2026, 9, 1), datetime(2026, 9, 2), "America/Sao_Paulo", agora=AGORA
    )

    assert inicio == datetime(2026, 9, 1, tzinfo=SAO_PAULO)
    assert fim == datetime(2026, 9, 2, tzinfo=SAO_PAULO)


def test_data_com_fuso_nao_muda():
    original = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    inicio, _ = resolver_periodo(original, None, "America/Sao_Paulo", agora=AGORA)

    assert inicio == original
    assert inicio.tzinfo is UTC


@pytest.mark.parametrize("timezone", ["Marte/Base", "", "nao existe"])
def test_timezone_invalido_da_erro(timezone):
    with pytest.raises(TimezoneInvalidoError):
        resolver_periodo(None, None, timezone, agora=AGORA)
