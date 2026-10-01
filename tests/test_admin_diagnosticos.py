"""Testes da consulta administrativa de diagnósticos (US-120 / DELTA-08).

Rodam em SQLite em memória (sem Postgres/container). Só as tabelas necessárias
são criadas, e `JSONB` é compilado como `JSON` no dialeto SQLite (apenas para
teste; produção continua JSONB).

`current_active_user` é sobrescrito com um usuário de papel configurável,
então `require_admin` roda de verdade — só a validação do JWT é substituída.
"""

import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.auth.users import current_active_user
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AuditoriaAcesso,
    ClassificacaoDiagnostico,
    Diagnostico,
    Imagem,
    User,
)


@compiles(JSONB, "sqlite")
def _jsonb_como_json_no_sqlite(type_, compiler, **kw):
    return "JSON"


pytestmark = pytest.mark.asyncio

BASE = "/api/v1/admin/diagnosticos"

ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
PROFISSIONAL_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
PACIENTE_A = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
PACIENTE_B = uuid.UUID("00000000-0000-0000-0000-0000000000c2")

DATA_BASE = datetime(2099, 8, 1, 9, 0, tzinfo=UTC)

TABELAS = [
    User.__table__,
    ClassificacaoDiagnostico.__table__,
    Diagnostico.__table__,
    Imagem.__table__,
    AuditoriaAcesso.__table__,
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
async def dados(session_factory) -> dict[str, dict[str, Diagnostico]]:
    """Semeia usuários, classificações e diagnósticos.

    d1 concluido / normal     / A / dia 0 (revisado)
    d2 concluido / intima     / A / dia 1
    d3 aguardando_revisao / social / B / dia 2
    d4 processando / sem classificação / B / dia 3
    d5 falha       / sem classificação / A / dia 4 (com erro)
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

        def _d(n, paciente, status, cls, dia, **extra):
            return Diagnostico(
                paciente_id=paciente,
                anamnese_id=n,
                classificacao_id=cls.id if cls else None,
                status=status,
                data_diagnostico=DATA_BASE + timedelta(days=dia),
                **extra,
            )

        d1 = _d(
            1,
            PACIENTE_A,
            "concluido",
            normal,
            0,
            escala_saburra=1,
            confianca_ia=0.91,
            profissional_revisor_id=PROFISSIONAL_ID,
            data_revisao=DATA_BASE + timedelta(days=1),
            observacoes_revisao="ok",
        )
        d2 = _d(2, PACIENTE_A, "concluido", intima, 1, escala_saburra=3, confianca_ia=0.8)
        d3 = _d(3, PACIENTE_B, "aguardando_revisao", social, 2, escala_saburra=5, confianca_ia=0.7)
        d4 = _d(4, PACIENTE_B, "processando", None, 3)
        d5 = _d(5, PACIENTE_A, "falha", None, 4, erro="timeout do modelo")
        db.add_all([d1, d2, d3, d4, d5])
        await db.flush()

        db.add(
            Imagem(
                diagnostico_id=d1.id,
                url_arquivo="/api/v1/diagnosticos/imagens/segredo.jpg",
                ordem=1,
                parametros_captura={"iso": 100},
            )
        )
        await db.commit()

        return {"d": {"d1": d1, "d2": d2, "d3": d3, "d4": d4, "d5": d5}}


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


async def _contar(session_factory, model) -> int:
    async with session_factory() as db:
        return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _auditorias(session_factory) -> list[AuditoriaAcesso]:
    async with session_factory() as db:
        return list((await db.execute(select(AuditoriaAcesso))).scalars().all())


# ---------------------------------------------------------------------------
# Acesso: somente admin
# ---------------------------------------------------------------------------


async def test_sem_token_retorna_401(http, dados) -> None:
    assert (await http.get(BASE)).status_code == 401
    assert (await http.get(f"{BASE}/1")).status_code == 401


@pytest.mark.parametrize("role", ["paciente", "profissional"])
async def test_outros_papeis_recebem_403_na_lista_e_no_detalhe(
    http, dados, como, session_factory, role
) -> None:
    como(role)
    d1 = dados["d"]["d1"]

    assert (await http.get(BASE)).status_code == 403
    assert (await http.get(f"{BASE}/{d1.id}")).status_code == 403
    # 403 não pode gerar auditoria de abertura
    assert await _contar(session_factory, AuditoriaAcesso) == 0


# ---------------------------------------------------------------------------
# Lista: filtros, total, paginação
# ---------------------------------------------------------------------------


async def test_lista_admin_sem_filtros_traz_todos_e_minimiza_dados(http, dados, como) -> None:
    como("admin")
    r = await http.get(BASE)

    assert r.status_code == 200
    corpo = r.json()
    assert corpo["total"] == 5
    assert corpo["total_paginas"] == 1
    assert len(corpo["itens"]) == 5

    for item in corpo["itens"]:
        assert set(item) == {
            "id",
            "paciente_id",
            "data_diagnostico",
            "status",
            "classificacao",
            "tem_revisao",
        }

    bruto = r.text
    for proibido in ("imagens", "url_arquivo", "anamnese", "respostas", "segredo.jpg", "email"):
        assert proibido not in bruto


async def test_filtra_por_status(http, dados, como) -> None:
    como("admin")
    r = await http.get(BASE, params={"status": "concluido"})

    assert r.json()["total"] == 2
    assert {i["status"] for i in r.json()["itens"]} == {"concluido"}


async def test_filtra_por_classificacao_codigo(http, dados, como) -> None:
    como("admin")
    r = await http.get(BASE, params={"classificacao": "halitose_intima"})

    corpo = r.json()
    assert corpo["total"] == 1
    assert corpo["itens"][0]["classificacao"]["codigo"] == "halitose_intima"


async def test_filtra_por_paciente(http, dados, como) -> None:
    como("admin")
    r = await http.get(BASE, params={"paciente_id": str(PACIENTE_B)})

    corpo = r.json()
    assert corpo["total"] == 2
    assert {i["paciente_id"] for i in corpo["itens"]} == {str(PACIENTE_B)}


async def test_filtra_por_periodo_com_datas_inclusivas(http, dados, como) -> None:
    como("admin")
    inicio = (DATA_BASE + timedelta(days=1)).date().isoformat()
    fim = (DATA_BASE + timedelta(days=3)).date().isoformat()

    r = await http.get(BASE, params={"data_inicio": inicio, "data_fim": fim})

    ids = {i["id"] for i in r.json()["itens"]}
    esperados = {dados["d"][k].id for k in ("d2", "d3", "d4")}
    assert ids == esperados
    assert r.json()["total"] == 3


async def test_combina_filtros(http, dados, como) -> None:
    como("admin")
    r = await http.get(BASE, params={"paciente_id": str(PACIENTE_A), "status": "concluido"})

    assert r.json()["total"] == 2


async def test_sem_classificacao_traz_processando_e_falha(http, dados, como) -> None:
    """'Status nulo' do escopo: diagnósticos sem classificação (classificacao_id NULL)."""
    como("admin")
    r = await http.get(BASE, params={"sem_classificacao": "true"})

    corpo = r.json()
    assert corpo["total"] == 2
    assert {i["status"] for i in corpo["itens"]} == {"processando", "falha"}
    assert all(i["classificacao"] is None for i in corpo["itens"])


async def test_total_reflete_filtro_e_nao_a_pagina(http, dados, como) -> None:
    como("admin")
    r = await http.get(BASE, params={"status": "concluido", "limite": 1})

    corpo = r.json()
    assert len(corpo["itens"]) == 1
    assert corpo["total"] == 2
    assert corpo["total_paginas"] == 2


async def test_paginacao_estavel_com_datas_iguais(http, session_factory, como) -> None:
    """Muitos diagnósticos com a MESMA data: `id` desempata, sem repetir/pular itens."""
    async with session_factory() as db:
        db.add(User(id=PACIENTE_A, name="A", email="a@x.io", hashed_password="x", role="paciente"))
        for n in range(1, 6):
            db.add(
                Diagnostico(
                    paciente_id=PACIENTE_A,
                    anamnese_id=n,
                    status="concluido",
                    data_diagnostico=DATA_BASE,
                )
            )
        await db.commit()

    como("admin")
    vistos: list[int] = []
    for pagina in (1, 2, 3):
        r = await http.get(BASE, params={"limite": 2, "pagina": pagina})
        corpo = r.json()
        assert corpo["total"] == 5
        assert corpo["total_paginas"] == 3
        vistos += [i["id"] for i in corpo["itens"]]

    assert len(vistos) == 5
    assert len(set(vistos)) == 5
    assert vistos == sorted(vistos, reverse=True)  # data_desc + id desc

    r = await http.get(BASE, params={"limite": 5, "ordem": "data_asc"})
    ids_asc = [i["id"] for i in r.json()["itens"]]
    assert ids_asc == sorted(ids_asc)


@pytest.mark.parametrize(
    "params",
    [
        {"pagina": 0},
        {"limite": 0},
        {"limite": 51},
        {"ordem": "aleatoria"},
        {"status": "inexistente"},
        {"data_inicio": "2099-09-10", "data_fim": "2099-09-01"},
        {"data_inicio": "ontem"},
        {"sem_classificacao": "true", "classificacao": "halito_normal"},
    ],
)
async def test_filtros_invalidos_retornam_400(http, dados, como, params) -> None:
    como("admin")
    assert (await http.get(BASE, params=params)).status_code == 400


async def test_paciente_id_malformado_retorna_422(http, dados, como) -> None:
    como("admin")
    assert (await http.get(BASE, params={"paciente_id": "abc"})).status_code == 422


# ---------------------------------------------------------------------------
# Detalhe: contexto mínimo, blocos distintos, somente leitura
# ---------------------------------------------------------------------------


async def test_detalhe_separa_automatica_revisao_e_dataset(http, dados, como) -> None:
    como("admin")
    d1 = dados["d"]["d1"]
    r = await http.get(f"{BASE}/{d1.id}")

    assert r.status_code == 200
    corpo = r.json()

    assert corpo["automatica"]["classificacao"]["codigo"] == "halito_normal"
    assert corpo["automatica"]["escala_saburra"] == 1
    assert corpo["automatica"]["confianca_ia"] == pytest.approx(0.91)

    assert corpo["revisao"]["profissional_revisor_id"] == str(PROFISSIONAL_ID)
    assert corpo["revisao"]["observacoes"] == "ok"

    assert corpo["dataset"] == {
        "disponivel": False,
        "motivo": "pendente de decisão DEC-04/DEC-07",
    }

    assert corpo["qtd_imagens"] == 1
    assert corpo["anamnese_id"] == 1


async def test_detalhe_minimiza_dados_sensiveis(http, dados, como) -> None:
    como("admin")
    r = await http.get(f"{BASE}/{dados['d']['d1'].id}")

    for proibido in (
        "url_arquivo",
        "segredo.jpg",
        "parametros_captura",
        "respostas",
        "email",
        "hashed_password",
        "paciente_nome",
    ):
        assert proibido not in r.text
    assert "imagens" not in r.json()
    assert "anamnese" not in r.json()


async def test_detalhe_sem_classificacao_e_sem_revisao(http, dados, como) -> None:
    como("admin")
    r = await http.get(f"{BASE}/{dados['d']['d5'].id}")

    corpo = r.json()
    assert corpo["automatica"] == {
        "classificacao": None,
        "escala_saburra": None,
        "confianca_ia": None,
    }
    assert corpo["revisao"] is None
    assert corpo["erro"] == "timeout do modelo"


async def test_detalhe_inexistente_retorna_404_sem_auditoria(
    http, dados, como, session_factory
) -> None:
    como("admin")

    assert (await http.get(f"{BASE}/999999")).status_code == 404
    assert await _contar(session_factory, AuditoriaAcesso) == 0


async def test_detalhe_e_somente_leitura_nao_processa_diagnostico(
    http, dados, como, session_factory
) -> None:
    """O detalhe do paciente dispara o mock (escreve no banco); o do admin não."""
    como("admin")
    d4 = dados["d"]["d4"]  # processando

    r = await http.get(f"{BASE}/{d4.id}")

    assert r.json()["status"] == "processando"
    async with session_factory() as db:
        atual = await db.get(Diagnostico, d4.id)
        assert atual.status == "processando"
        assert atual.classificacao_id is None


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------


async def test_abrir_detalhe_registra_auditoria(http, dados, como, session_factory) -> None:
    como("admin")
    d2 = dados["d"]["d2"]

    assert (await http.get(f"{BASE}/{d2.id}")).status_code == 200

    registros = await _auditorias(session_factory)
    assert len(registros) == 1
    assert registros[0].ator_id == ADMIN_ID
    assert registros[0].acao == "diagnostico.detalhe.aberto"
    assert registros[0].recurso_tipo == "diagnostico"
    assert registros[0].recurso_id == str(d2.id)
    assert registros[0].criado_em is not None

    # cada abertura gera um registro
    await http.get(f"{BASE}/{d2.id}")
    assert await _contar(session_factory, AuditoriaAcesso) == 2


async def test_listar_nao_registra_auditoria(http, dados, como, session_factory) -> None:
    como("admin")

    await http.get(BASE)

    assert await _contar(session_factory, AuditoriaAcesso) == 0


# ---------------------------------------------------------------------------
# Sem mutation / sem exportação
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["paciente", "profissional", "admin"])
@pytest.mark.parametrize("metodo", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize("sufixo", ["", "/1", "/1/rotulo", "/exportar"])
async def test_nenhum_papel_consegue_mutar(
    http, dados, como, session_factory, role, metodo, sufixo
) -> None:
    """Nenhuma rota de escrita existe: 403 (não-admin) ou 404/405, e o banco não muda."""
    como(role)
    antes = (
        await _contar(session_factory, Diagnostico),
        await _contar(session_factory, AuditoriaAcesso),
    )

    r = await http.request(metodo.upper(), f"{BASE}{sufixo}", json={"rotulo": "x"})

    assert r.status_code in (403, 404, 405)
    depois = (
        await _contar(session_factory, Diagnostico),
        await _contar(session_factory, AuditoriaAcesso),
    )
    assert antes == depois

    async with session_factory() as db:
        d1 = await db.get(Diagnostico, dados["d"]["d1"].id)
        assert d1.status == "concluido"
        assert d1.classificacao_id is not None


async def test_openapi_admin_expoe_apenas_get() -> None:
    """Contrato: sob /admin/diagnosticos só existe leitura (sem rótulo, sem download/importação)."""
    paths = {p: v for p, v in app.openapi()["paths"].items() if "/admin/diagnosticos" in p}

    assert paths, "rotas admin não registradas"
    for path, operacoes in paths.items():
        assert set(operacoes) == {"get"}, path
        assert not any(t in path for t in ("export", "download", "import", "rotulo", "label"))
