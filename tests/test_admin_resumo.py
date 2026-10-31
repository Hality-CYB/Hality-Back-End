"""Testes do resumo administrativo (TASK-103).

Rodam em SQLite em memoria, entao nao precisa de Postgres nem de Docker
(igual o test_admin_diagnosticos.py).
"""

import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.users import current_active_user
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import ClassificacaoDiagnostico, Diagnostico, User
from app.services import admin_resumo_service

pytestmark = pytest.mark.asyncio

URL = "/api/v1/admin/resumo"

ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
PROFISSIONAL_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
PACIENTE_A = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
PACIENTE_B = uuid.UUID("00000000-0000-0000-0000-0000000000c2")

TABELAS = [
    User.__table__,
    ClassificacaoDiagnostico.__table__,
    Diagnostico.__table__,
]

# agosto de 2026 inteiro, em UTC
AGOSTO = {"inicio": "2026-08-01T00:00:00+00:00", "fim": "2026-08-31T23:59:59+00:00"}


# fixtures


@pytest_asyncio.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=TABELAS))

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    yield factory

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def dados(session_factory) -> dict[str, int]:
    """Cria usuarios, classificacoes e alguns diagnosticos pequenos pra testar.

    d1 concluido, normal, revisado, 01/08 09:00 UTC
    d2 concluido, intima, sem revisao, 02/08 02:00 UTC (01/08 23:00 em Sao Paulo)
    d3 aguardando_revisao, social, 03/08
    d4 processando, sem classificacao, 04/08
    d5 falha, sem classificacao, 05/08
    d6 aguardando_revisao, social, 10/09 (fora de agosto)
    d7 concluido, normal, tem revisor mas sem data de revisao, 06/08 (nao conta como revisado)

    Devolve os ids das classificacoes.
    """
    async with session_factory() as db:
        for uid, nome, role in (
            (ADMIN_ID, "Admin", "admin"),
            (PROFISSIONAL_ID, "Prof", "profissional"),
            (PACIENTE_A, "Paciente A", "paciente"),
            (PACIENTE_B, "Paciente B", "paciente"),
        ):
            db.add(
                User(
                    id=uid,
                    name=nome,
                    email=f"{nome.lower().replace(' ', '')}@hality.local",
                    hashed_password="x",
                    role=role,
                )
            )

        normal = ClassificacaoDiagnostico(codigo="halito_normal", nome_exibicao="Normal", ordem=1)
        intima = ClassificacaoDiagnostico(codigo="halitose_intima", nome_exibicao="Íntima", ordem=2)
        social = ClassificacaoDiagnostico(
            codigo="mau_halito_social", nome_exibicao="Social", ordem=3
        )
        db.add_all([normal, intima, social])
        await db.flush()

        def _d(n, paciente, status, classificacao, momento, **extra):
            return Diagnostico(
                paciente_id=paciente,
                anamnese_id=n,
                classificacao_id=classificacao.id if classificacao else None,
                status=status,
                data_diagnostico=momento,
                **extra,
            )

        db.add_all(
            [
                _d(
                    1,
                    PACIENTE_A,
                    "concluido",
                    normal,
                    datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
                    profissional_revisor_id=PROFISSIONAL_ID,
                    data_revisao=datetime(2026, 8, 2, 9, 0, tzinfo=UTC),
                ),
                _d(2, PACIENTE_A, "concluido", intima, datetime(2026, 8, 2, 2, 0, tzinfo=UTC)),
                _d(3, PACIENTE_B, "aguardando_revisao", social, datetime(2026, 8, 3, tzinfo=UTC)),
                _d(4, PACIENTE_B, "processando", None, datetime(2026, 8, 4, tzinfo=UTC)),
                _d(5, PACIENTE_A, "falha", None, datetime(2026, 8, 5, tzinfo=UTC)),
                _d(6, PACIENTE_B, "aguardando_revisao", social, datetime(2026, 9, 10, tzinfo=UTC)),
                _d(
                    7,
                    PACIENTE_A,
                    "concluido",
                    normal,
                    datetime(2026, 8, 6, tzinfo=UTC),
                    profissional_revisor_id=PROFISSIONAL_ID,
                ),
            ]
        )
        await db.commit()

        return {"normal": normal.id, "intima": intima.id, "social": social.id}


ComoUsuario = Callable[[str], None]


@pytest.fixture
def como() -> ComoUsuario:
    def _como(role: str) -> None:
        app.dependency_overrides[current_active_user] = lambda: SimpleNamespace(
            id=ADMIN_ID if role == "admin" else PROFISSIONAL_ID,
            role=role,
            is_active=True,
        )

    return _como


@pytest_asyncio.fixture
async def http(session_factory) -> AsyncGenerator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# so admin pode acessar


async def test_sem_token_retorna_401(http, dados) -> None:
    assert (await http.get(URL)).status_code == 401


@pytest.mark.parametrize("role", ["paciente", "profissional"])
async def test_quem_nao_e_admin_recebe_403(http, dados, como, role) -> None:
    como(role)

    assert (await http.get(URL, params=AGOSTO)).status_code == 403


# formato da resposta e contas


async def test_admin_recebe_o_contrato_do_resumo(http, dados, como) -> None:
    como("admin")

    response = await http.get(URL, params={**AGOSTO, "timezone": "America/Sao_Paulo"})

    assert response.status_code == 200
    corpo = response.json()
    assert set(corpo) == {"periodo", "diagnosticos", "revisao", "halitose"}
    assert set(corpo["periodo"]) == {"inicio", "fim", "timezone"}
    assert set(corpo["diagnosticos"]) == {"total", "por_classificacao", "por_status"}
    assert set(corpo["revisao"]) == {"pendentes", "revisados"}
    assert corpo["periodo"]["timezone"] == "America/Sao_Paulo"
    # ainda nao tem a regra clinica, entao fica null (e nao zero)
    assert corpo["halitose"] is None


async def test_agregacoes_batem_com_a_fixture(http, dados, como) -> None:
    como("admin")

    corpo = (await http.get(URL, params=AGOSTO)).json()

    assert corpo["diagnosticos"] == {
        "total": 6,
        "por_classificacao": {
            str(dados["normal"]): 2,
            str(dados["intima"]): 1,
            str(dados["social"]): 1,
            "sem_classificacao": 2,
        },
        "por_status": {
            "aguardando_revisao": 1,
            "concluido": 3,
            "falha": 1,
            "processando": 1,
        },
    }
    assert corpo["revisao"] == {"pendentes": 1, "revisados": 1}


async def test_periodo_deixa_de_fora_diagnosticos_de_outro_mes(http, dados, como) -> None:
    como("admin")

    setembro = {"inicio": "2026-09-01T00:00:00+00:00", "fim": "2026-09-30T23:59:59+00:00"}
    corpo = (await http.get(URL, params=setembro)).json()

    assert corpo["diagnosticos"]["total"] == 1
    assert corpo["diagnosticos"]["por_status"] == {"aguardando_revisao": 1}
    assert corpo["revisao"] == {"pendentes": 1, "revisados": 0}


async def test_periodo_sem_dados_volta_zerado_e_nao_da_erro(http, dados, como) -> None:
    como("admin")

    vazio = {"inicio": "2027-01-01T00:00:00+00:00", "fim": "2027-01-31T23:59:59+00:00"}
    response = await http.get(URL, params=vazio)

    assert response.status_code == 200
    corpo = response.json()
    assert corpo["diagnosticos"] == {"total": 0, "por_classificacao": {}, "por_status": {}}
    assert corpo["revisao"] == {"pendentes": 0, "revisados": 0}
    assert corpo["halitose"] is None


async def test_sem_parametros_usa_os_ultimos_30_dias_em_utc(http, dados, como) -> None:
    como("admin")

    response = await http.get(URL)

    assert response.status_code == 200
    periodo = response.json()["periodo"]
    assert periodo["timezone"] == "UTC"
    inicio = datetime.fromisoformat(periodo["inicio"])
    fim = datetime.fromisoformat(periodo["fim"])
    assert fim - inicio == timedelta(days=30)


# timezone


async def test_data_sem_fuso_usa_o_timezone_informado(http, dados, como) -> None:
    como("admin")

    # o dia 01/08 em Sao Paulo vai de 01/08 03:00 UTC ate 02/08 02:59 UTC,
    # entao pega o d1 e o d2. Em UTC o mesmo dia pega so o d1.
    dia = {"inicio": "2026-08-01T00:00:00", "fim": "2026-08-01T23:59:59"}

    sao_paulo = (await http.get(URL, params={**dia, "timezone": "America/Sao_Paulo"})).json()
    utc = (await http.get(URL, params=dia)).json()

    assert sao_paulo["diagnosticos"]["total"] == 2
    assert sao_paulo["periodo"]["inicio"] == "2026-08-01T00:00:00-03:00"
    assert utc["diagnosticos"]["total"] == 1


async def test_timezone_invalido_retorna_400(http, dados, como) -> None:
    como("admin")

    response = await http.get(URL, params={**AGOSTO, "timezone": "Marte/Base"})

    assert response.status_code == 400
    assert response.json()["detail"] == "timezone invalido"


# periodos invalidos


async def test_intervalo_invertido_retorna_400(http, dados, como) -> None:
    como("admin")

    invertido = {"inicio": AGOSTO["fim"], "fim": AGOSTO["inicio"]}
    response = await http.get(URL, params=invertido)

    assert response.status_code == 400
    assert response.json()["detail"] == "periodo invalido"


async def test_periodo_acima_do_limite_retorna_400(http, dados, como) -> None:
    como("admin")

    longo = {"inicio": "2024-01-01T00:00:00+00:00", "fim": "2026-01-01T00:00:00+00:00"}
    response = await http.get(URL, params=longo)

    assert response.status_code == 400
    assert str(admin_resumo_service.LIMITE_PERIODO_DIAS) in response.json()["detail"]


async def test_periodo_exatamente_no_limite_e_aceito(http, dados, como) -> None:
    como("admin")

    fim = datetime(2026, 12, 31, tzinfo=UTC)
    inicio = fim - timedelta(days=admin_resumo_service.LIMITE_PERIODO_DIAS)
    response = await http.get(URL, params={"inicio": inicio.isoformat(), "fim": fim.isoformat()})

    assert response.status_code == 200


async def test_data_malformada_retorna_422(http, dados, como) -> None:
    como("admin")

    assert (await http.get(URL, params={"inicio": "ontem"})).status_code == 422
