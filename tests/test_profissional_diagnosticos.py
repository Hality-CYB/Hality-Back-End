import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from fastapi_users_db_sqlalchemy.generics import GUID
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.auth.users import current_active_user
from app.db import diagnostico_queries
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    Anamnese,
    ClassificacaoDiagnostico,
    Diagnostico,
    DiagnosticoRevisao,
    Imagem,
    PacienteProfissional,
    Profissional,
    User,
)
from app.services import diagnostico_mock


@compiles(JSONB, "sqlite")
def _jsonb_como_json_no_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(GUID, "sqlite")
def _guid_como_char_no_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


pytestmark = pytest.mark.asyncio

BASE = "/api/v1/profissional/diagnosticos"

PROFISSIONAL_A = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
PROFISSIONAL_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")

PACIENTE_A = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
PACIENTE_B = uuid.UUID("00000000-0000-0000-0000-0000000000c2")

DATA_BASE = datetime(
    2099,
    8,
    1,
    9,
    0,
    tzinfo=UTC,
)

TABELAS = [
    User.__table__,
    Profissional.__table__,
    PacienteProfissional.__table__,
    Anamnese.__table__,
    ClassificacaoDiagnostico.__table__,
    Diagnostico.__table__,
    DiagnosticoRevisao.__table__,
    Imagem.__table__,
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={
            "check_same_thread": False,
        },
    )

    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c,
                tables=TABELAS,
            )
        )

    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def _override_get_db() -> AsyncGenerator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    yield factory

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def dados(
    session_factory,
) -> dict:
    async with session_factory() as db:
        usuarios = [
            User(
                id=PROFISSIONAL_A,
                name="Profissional A",
                email="prof.a@hality.local",
                hashed_password="x",
                role="profissional",
            ),
            User(
                id=PROFISSIONAL_B,
                name="Profissional B",
                email="prof.b@hality.local",
                hashed_password="x",
                role="profissional",
            ),
            User(
                id=PACIENTE_A,
                name="Paciente A",
                email="paciente.a@hality.local",
                hashed_password="x",
                role="paciente",
            ),
            User(
                id=PACIENTE_B,
                name="Paciente B",
                email="paciente.b@hality.local",
                hashed_password="x",
                role="paciente",
            ),
        ]

        db.add_all(usuarios)
        await db.flush()

        db.add_all(
            [
                Profissional(
                    usuario_id=PROFISSIONAL_A,
                    especialidade="Periodontia",
                ),
                Profissional(
                    usuario_id=PROFISSIONAL_B,
                    especialidade="Odontologia",
                ),
            ]
        )

        await db.flush()

        # A possui vínculo ativo com o profissional autenticado.
        db.add(
            PacienteProfissional(
                paciente_id=PACIENTE_A,
                profissional_id=PROFISSIONAL_A,
                ativo=True,
            )
        )

        # Existe histórico entre B e A, mas o vínculo foi encerrado.
        db.add(
            PacienteProfissional(
                paciente_id=PACIENTE_B,
                profissional_id=PROFISSIONAL_A,
                ativo=False,
                encerrado_em=DATA_BASE,
            )
        )

        # Atualmente B pertence ao profissional B.
        db.add(
            PacienteProfissional(
                paciente_id=PACIENTE_B,
                profissional_id=PROFISSIONAL_B,
                ativo=True,
            )
        )

        normal = ClassificacaoDiagnostico(
            codigo="halito_normal",
            nome_exibicao="Normal",
            ordem=1,
        )

        intima = ClassificacaoDiagnostico(
            codigo="halitose_intima",
            nome_exibicao="Íntima",
            ordem=2,
        )

        social = ClassificacaoDiagnostico(
            codigo="mau_halito_social",
            nome_exibicao="Social",
            ordem=3,
        )

        db.add_all(
            [
                normal,
                intima,
                social,
            ]
        )

        await db.flush()

        resposta = [
            {
                "pergunta_id": "teste",
                "enunciado": "Pergunta de teste?",
                "tipo": "boolean",
                "resposta": "Sim",
                "valor": True,
                "tipo_resposta": "bool",
            }
        ]

        anamneses = []

        for numero, paciente in enumerate(
            [
                PACIENTE_A,
                PACIENTE_A,
                PACIENTE_A,
                PACIENTE_A,
                PACIENTE_B,
            ],
            start=1,
        ):
            anamnese = Anamnese(
                paciente_id=paciente,
                executor_id=paciente,
                data_preenchimento=(DATA_BASE + timedelta(days=numero - 1)),
                id_versao_questionario="teste-v1",
                respostas=resposta,
            )

            db.add(anamnese)
            anamneses.append(anamnese)

        await db.flush()

        def _diagnostico(
            indice,
            paciente,
            status_diagnostico,
            classificacao,
            dia,
            **extra,
        ):
            return Diagnostico(
                paciente_id=paciente,
                executor_id=paciente,
                anamnese_id=anamneses[indice - 1].id,
                classificacao_id=(classificacao.id if classificacao is not None else None),
                status=status_diagnostico,
                data_diagnostico=(DATA_BASE + timedelta(days=dia)),
                **extra,
            )

        # Paciente A — acessível ao profissional A.
        d1 = _diagnostico(
            1,
            PACIENTE_A,
            "concluido",
            normal,
            0,
            escala_saburra=1,
            confianca_ia=0.91,
        )

        d2 = _diagnostico(
            2,
            PACIENTE_A,
            "aguardando_revisao",
            intima,
            1,
            escala_saburra=3,
            confianca_ia=0.82,
        )

        d3 = _diagnostico(
            3,
            PACIENTE_A,
            "processando",
            None,
            2,
        )

        d4 = _diagnostico(
            4,
            PACIENTE_A,
            "falha",
            None,
            3,
            erro="timeout do modelo",
        )

        # Paciente B — não acessível ao profissional A.
        d5 = _diagnostico(
            5,
            PACIENTE_B,
            "concluido",
            social,
            4,
            escala_saburra=5,
            confianca_ia=0.73,
        )

        db.add_all(
            [
                d1,
                d2,
                d3,
                d4,
                d5,
            ]
        )

        await db.flush()

        db.add(
            Imagem(
                diagnostico_id=d1.id,
                url_arquivo=("/api/v1/diagnosticos/imagens/imagem-profissional.jpg"),
                ordem=1,
                parametros_captura={
                    "iso": 100,
                },
                data_captura=DATA_BASE,
            )
        )

        await db.commit()

        return {
            "d": {
                "d1": d1,
                "d2": d2,
                "d3": d3,
                "d4": d4,
                "d5": d5,
            },
            "classificacoes": {
                "normal": normal,
                "intima": intima,
                "social": social,
            },
        }


ComoUsuario = Callable[[str, uuid.UUID], None]


@pytest.fixture
def como() -> ComoUsuario:
    def _como(
        role: str = "profissional",
        usuario_id: uuid.UUID = PROFISSIONAL_A,
    ) -> None:
        app.dependency_overrides[current_active_user] = lambda: SimpleNamespace(
            id=usuario_id,
            role=role,
            is_active=True,
        )

    return _como


@pytest_asyncio.fixture
async def http(
    session_factory,
) -> AsyncGenerator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def _contar(
    session_factory,
    model,
) -> int:
    async with session_factory() as db:
        return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _revisoes(
    session_factory,
    diagnostico_id: int,
) -> list[DiagnosticoRevisao]:
    async with session_factory() as db:
        resultado = await db.execute(
            select(DiagnosticoRevisao)
            .where(DiagnosticoRevisao.diagnostico_id == diagnostico_id)
            .order_by(DiagnosticoRevisao.versao.asc())
        )

        return list(resultado.scalars().all())


# ---------------------------------------------------------------------------
# Autorização
# ---------------------------------------------------------------------------


async def test_sem_token_retorna_401(
    http,
    dados,
) -> None:
    d1 = dados["d"]["d1"]

    assert (await http.get(BASE)).status_code == 401

    assert (await http.get(f"{BASE}/{d1.id}")).status_code == 401

    assert (
        await http.patch(
            f"{BASE}/{d1.id}/revisao",
            json={
                "classificacao": "halito_normal",
                "version": 0,
            },
        )
    ).status_code == 401


@pytest.mark.parametrize(
    "role",
    [
        "paciente",
        "admin",
    ],
)
async def test_somente_profissional_pode_acessar_rotas(
    http,
    dados,
    como,
    role,
) -> None:
    como(role)

    d1 = dados["d"]["d1"]

    assert (await http.get(BASE)).status_code == 403

    assert (await http.get(f"{BASE}/{d1.id}")).status_code == 403

    assert (
        await http.patch(
            f"{BASE}/{d1.id}/revisao",
            json={
                "classificacao": "halito_normal",
                "version": 0,
            },
        )
    ).status_code == 403


# ---------------------------------------------------------------------------
# Listagem
# ---------------------------------------------------------------------------


async def test_lista_intersecta_vinculo_ativo(
    http,
    dados,
    como,
) -> None:
    como()

    response = await http.get(BASE)

    assert response.status_code == 200

    corpo = response.json()

    assert corpo["total"] == 4

    ids = {item["id"] for item in corpo["itens"]}

    assert ids == {
        dados["d"]["d1"].id,
        dados["d"]["d2"].id,
        dados["d"]["d3"].id,
        dados["d"]["d4"].id,
    }

    assert dados["d"]["d5"].id not in ids

    assert {item["paciente"]["id"] for item in corpo["itens"]} == {
        str(PACIENTE_A),
    }
    assert {item["status"] for item in corpo["itens"]} == {
        "concluido",
        "aguardando_revisao",
        "processando",
        "falha",
    }
    assert all(item["status"] != "revisado" for item in corpo["itens"])


async def test_paciente_id_nao_concede_acesso(
    http,
    dados,
    como,
) -> None:
    como()

    response = await http.get(
        BASE,
        params={
            "paciente_id": str(PACIENTE_B),
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["itens"] == []


async def test_lista_filtra_status(
    http,
    dados,
    como,
) -> None:
    como()

    response = await http.get(
        BASE,
        params={
            "status": "concluido",
        },
    )

    assert response.status_code == 200

    corpo = response.json()

    assert corpo["total"] == 1
    assert corpo["itens"][0]["id"] == (dados["d"]["d1"].id)


async def test_lista_filtra_periodo(
    http,
    dados,
    como,
) -> None:
    como()

    response = await http.get(
        BASE,
        params={
            "data_inicio": (DATA_BASE + timedelta(days=1)).date().isoformat(),
            "data_fim": (DATA_BASE + timedelta(days=2)).date().isoformat(),
        },
    )

    assert response.status_code == 200

    ids = {item["id"] for item in response.json()["itens"]}

    assert ids == {
        dados["d"]["d2"].id,
        dados["d"]["d3"].id,
    }


async def test_lista_respeita_paginacao_e_ordem(
    http,
    dados,
    como,
) -> None:
    como()

    primeira = await http.get(
        BASE,
        params={
            "pagina": 1,
            "limite": 2,
            "ordem": "data_desc",
        },
    )

    segunda = await http.get(
        BASE,
        params={
            "pagina": 2,
            "limite": 2,
            "ordem": "data_desc",
        },
    )

    assert primeira.status_code == 200
    assert segunda.status_code == 200

    assert primeira.json()["total"] == 4
    assert primeira.json()["total_paginas"] == 2

    ids_1 = [item["id"] for item in primeira.json()["itens"]]

    ids_2 = [item["id"] for item in segunda.json()["itens"]]

    assert set(ids_1).isdisjoint(ids_2)

    assert ids_1 + ids_2 == [
        dados["d"]["d4"].id,
        dados["d"]["d3"].id,
        dados["d"]["d2"].id,
        dados["d"]["d1"].id,
    ]


@pytest.mark.parametrize(
    "params",
    [
        {
            "pagina": 0,
        },
        {
            "limite": 0,
        },
        {
            "limite": 51,
        },
        {
            "ordem": "qualquer",
        },
        {
            "status": "inexistente",
        },
        {
            "data_inicio": "ontem",
        },
        {
            "data_inicio": "2099-09-10",
            "data_fim": "2099-09-01",
        },
    ],
)
async def test_filtros_invalidos_retornam_400(
    http,
    dados,
    como,
    params,
) -> None:
    como()

    response = await http.get(
        BASE,
        params=params,
    )

    assert response.status_code == 400


async def test_paciente_id_malformado_retorna_422(
    http,
    dados,
    como,
) -> None:
    como()

    response = await http.get(
        BASE,
        params={
            "paciente_id": "abc",
        },
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Detalhe
# ---------------------------------------------------------------------------


async def test_detalhe_profissional_retorna_contexto_clinico(
    http,
    dados,
    como,
) -> None:
    como()

    d1 = dados["d"]["d1"]

    response = await http.get(f"{BASE}/{d1.id}")

    assert response.status_code == 200

    corpo = response.json()

    assert corpo["id"] == d1.id
    assert corpo["status"] == "concluido"

    assert corpo["paciente"] == {
        "id": str(PACIENTE_A),
        "nome": "Paciente A",
    }

    assert corpo["anamnese"]["id"] == d1.anamnese_id
    assert corpo["anamnese"]["respostas"]

    assert corpo["automatico"]["classificacao"]["codigo"] == "halito_normal"

    assert corpo["automatico"]["escala_saburra"] == 1

    assert corpo["automatico"]["confianca_ia"] == pytest.approx(0.91)

    assert corpo["revisao"] is None
    assert corpo["historico_revisoes"] == []
    assert corpo["version"] == 0

    assert corpo["aviso_legal"]


async def test_detalhe_assina_url_da_imagem(
    http,
    dados,
    como,
) -> None:
    como()

    d1 = dados["d"]["d1"]

    response = await http.get(f"{BASE}/{d1.id}")

    assert response.status_code == 200

    imagens = response.json()["imagens"]

    assert len(imagens) == 1

    url = imagens[0]["url_arquivo"]

    assert "imagem-profissional.jpg" in url

    query = parse_qs(urlparse(url).query)

    assert "expira" in query
    assert "assinatura" in query


async def test_detalhe_sem_vinculo_ativo_retorna_404(
    http,
    dados,
    como,
) -> None:
    como()

    d5 = dados["d"]["d5"]

    response = await http.get(f"{BASE}/{d5.id}")

    assert response.status_code == 404


async def test_detalhe_inexistente_retorna_404(
    http,
    dados,
    como,
) -> None:
    como()

    response = await http.get(f"{BASE}/999999")

    assert response.status_code == 404


async def test_detalhe_profissional_nao_dispara_mock(
    http,
    dados,
    como,
    monkeypatch,
) -> None:
    como()

    processar = AsyncMock(
        side_effect=AssertionError("GET profissional não deve processar diagnóstico")
    )

    monkeypatch.setattr(
        diagnostico_mock,
        "processar_se_necessario",
        processar,
    )

    d3 = dados["d"]["d3"]

    response = await http.get(f"{BASE}/{d3.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "processando"
    assert response.json()["automatico"] is None

    processar.assert_not_awaited()


# ---------------------------------------------------------------------------
# Revisão profissional
# ---------------------------------------------------------------------------


async def test_primeira_revisao_cria_versao_um(
    http,
    dados,
    como,
    session_factory,
) -> None:
    como()

    d1 = dados["d"]["d1"]

    response = await http.patch(
        f"{BASE}/{d1.id}/revisao",
        json={
            "classificacao": "halitose_intima",
            "observacao": "Revisão clínica.",
            "version": 0,
        },
    )

    assert response.status_code == 200

    corpo = response.json()

    assert corpo["version"] == 1
    assert corpo["revisao"]["version"] == 1

    assert corpo["revisao"]["classificacao"]["codigo"] == "halitose_intima"

    assert corpo["revisao"]["profissional_id"] == str(PROFISSIONAL_A)

    assert corpo["revisao"]["observacao"] == "Revisão clínica."

    revisoes = await _revisoes(
        session_factory,
        d1.id,
    )

    assert len(revisoes) == 1
    assert revisoes[0].versao == 1
    assert revisoes[0].revisao_anterior_id is None
    assert revisoes[0].profissional_id == PROFISSIONAL_A


async def test_revisao_nao_sobrescreve_resultado_da_ia(
    http,
    dados,
    como,
    session_factory,
) -> None:
    como()

    d1 = dados["d"]["d1"]

    classificacao_automatica_id = dados["classificacoes"]["normal"].id

    response = await http.patch(
        f"{BASE}/{d1.id}/revisao",
        json={
            "classificacao": "halitose_intima",
            "version": 0,
        },
    )

    assert response.status_code == 200

    async with session_factory() as db:
        atual = await db.get(
            Diagnostico,
            d1.id,
        )

        assert atual.classificacao_id == classificacao_automatica_id

        assert atual.profissional_revisor_id == PROFISSIONAL_A

        assert atual.data_revisao is not None


async def test_ia_deixa_diagnostico_aguardando_revisao(
    dados,
    session_factory,
) -> None:
    d3 = dados["d"]["d3"]

    async with session_factory() as db:
        diagnostico = await db.get(Diagnostico, d3.id)
        # Passado o tempo de processamento do mock da IA.
        diagnostico.data_diagnostico = datetime.now(UTC) - timedelta(minutes=1)

        await diagnostico_mock.processar_se_necessario(db, diagnostico)

        assert diagnostico.status == "aguardando_revisao"
        assert diagnostico.classificacao_id is not None


async def test_revisao_marca_diagnostico_como_concluido(
    http,
    dados,
    como,
    session_factory,
) -> None:
    como()

    d2 = dados["d"]["d2"]

    response = await http.patch(
        f"{BASE}/{d2.id}/revisao",
        json={"classificacao": "halitose_intima", "version": 0},
    )

    assert response.status_code == 200

    async with session_factory() as db:
        atual = await db.get(Diagnostico, d2.id)

        assert atual.status == "concluido"

    detalhe = await http.get(f"{BASE}/{d2.id}")

    assert detalhe.json()["status"] == "concluido"


async def test_revisor_vem_do_token_e_nao_do_body(
    http,
    dados,
    como,
    session_factory,
) -> None:
    como()

    d1 = dados["d"]["d1"]

    response = await http.patch(
        f"{BASE}/{d1.id}/revisao",
        json={
            "classificacao": "halitose_intima",
            "observacao": "Teste",
            "version": 0,
            # Deve ser ignorado: não faz parte do contrato.
            "profissional_id": str(PROFISSIONAL_B),
        },
    )

    assert response.status_code == 200

    revisoes = await _revisoes(
        session_factory,
        d1.id,
    )

    assert len(revisoes) == 1

    assert revisoes[0].profissional_id == PROFISSIONAL_A


async def test_segunda_revisao_preserva_historico(
    http,
    dados,
    como,
    session_factory,
) -> None:
    como()

    d1 = dados["d"]["d1"]

    primeira = await http.patch(
        f"{BASE}/{d1.id}/revisao",
        json={
            "classificacao": "halitose_intima",
            "observacao": "Primeira",
            "version": 0,
        },
    )

    assert primeira.status_code == 200

    segunda = await http.patch(
        f"{BASE}/{d1.id}/revisao",
        json={
            "classificacao": "mau_halito_social",
            "observacao": "Segunda",
            "version": 1,
        },
    )

    assert segunda.status_code == 200
    assert segunda.json()["version"] == 2

    revisoes = await _revisoes(
        session_factory,
        d1.id,
    )

    assert [revisao.versao for revisao in revisoes] == [
        1,
        2,
    ]

    assert revisoes[1].revisao_anterior_id == revisoes[0].id

    detalhe = await http.get(f"{BASE}/{d1.id}")

    assert detalhe.status_code == 200

    corpo = detalhe.json()

    assert corpo["version"] == 2

    assert [item["version"] for item in corpo["historico_revisoes"]] == [
        1,
        2,
    ]

    assert [item["classificacao"]["codigo"] for item in corpo["historico_revisoes"]] == [
        "halitose_intima",
        "mau_halito_social",
    ]

    assert corpo["revisao"]["classificacao"]["codigo"] == "mau_halito_social"


async def test_version_desatualizada_retorna_409(
    http,
    dados,
    como,
    session_factory,
) -> None:
    como()

    d1 = dados["d"]["d1"]

    primeira = await http.patch(
        f"{BASE}/{d1.id}/revisao",
        json={
            "classificacao": "halitose_intima",
            "version": 0,
        },
    )

    assert primeira.status_code == 200

    stale = await http.patch(
        f"{BASE}/{d1.id}/revisao",
        json={
            "classificacao": "mau_halito_social",
            "version": 0,
        },
    )

    assert stale.status_code == 409

    revisoes = await _revisoes(
        session_factory,
        d1.id,
    )

    assert len(revisoes) == 1
    assert revisoes[0].versao == 1


async def test_classificacao_invalida_retorna_400(
    http,
    dados,
    como,
    session_factory,
) -> None:
    como()

    d1 = dados["d"]["d1"]

    response = await http.patch(
        f"{BASE}/{d1.id}/revisao",
        json={
            "classificacao": "inventada",
            "version": 0,
        },
    )

    assert response.status_code == 400

    assert (
        await _contar(
            session_factory,
            DiagnosticoRevisao,
        )
        == 0
    )


@pytest.mark.parametrize(
    "chave",
    [
        "d3",
        "d4",
    ],
)
async def test_processando_e_falha_nao_podem_ser_revisados(
    http,
    dados,
    como,
    chave,
) -> None:
    como()

    diagnostico = dados["d"][chave]

    response = await http.patch(
        f"{BASE}/{diagnostico.id}/revisao",
        json={
            "classificacao": "halito_normal",
            "version": 0,
        },
    )

    assert response.status_code == 409


async def test_revisao_sem_vinculo_ativo_retorna_404(
    http,
    dados,
    como,
    session_factory,
) -> None:
    como()

    d5 = dados["d"]["d5"]

    response = await http.patch(
        f"{BASE}/{d5.id}/revisao",
        json={
            "classificacao": "halito_normal",
            "version": 0,
        },
    )

    assert response.status_code == 404

    assert (
        await _contar(
            session_factory,
            DiagnosticoRevisao,
        )
        == 0
    )


async def test_observacao_excessiva_retorna_422(
    http,
    dados,
    como,
    session_factory,
) -> None:
    como()

    d1 = dados["d"]["d1"]

    response = await http.patch(
        f"{BASE}/{d1.id}/revisao",
        json={
            "classificacao": "halito_normal",
            "observacao": "x" * 2001,
            "version": 0,
        },
    )

    assert response.status_code == 422

    assert (
        await _contar(
            session_factory,
            DiagnosticoRevisao,
        )
        == 0
    )


# ---------------------------------------------------------------------------
# Concorrência / constraint
# ---------------------------------------------------------------------------


async def test_constraint_impede_duas_revisoes_da_mesma_versao(
    dados,
    session_factory,
) -> None:
    d1 = dados["d"]["d1"]
    classificacao = dados["classificacoes"]["normal"]

    async with session_factory() as db:
        primeira = DiagnosticoRevisao(
            diagnostico_id=d1.id,
            profissional_id=PROFISSIONAL_A,
            classificacao_id=classificacao.id,
            observacao=None,
            versao=1,
        )

        db.add(primeira)
        await db.commit()

    async with session_factory() as db:
        duplicada = DiagnosticoRevisao(
            diagnostico_id=d1.id,
            profissional_id=PROFISSIONAL_A,
            classificacao_id=classificacao.id,
            observacao=None,
            versao=1,
        )

        db.add(duplicada)

        with pytest.raises(IntegrityError):
            await db.commit()

        await db.rollback()


async def test_integrity_error_de_corrida_vira_409(
    http,
    dados,
    como,
    monkeypatch,
) -> None:
    como()

    d1 = dados["d"]["d1"]

    inserir = AsyncMock(
        side_effect=IntegrityError(
            "INSERT",
            {},
            Exception("uq_diagnostico_revisoes_diagnostico_versao"),
        )
    )

    monkeypatch.setattr(
        diagnostico_queries,
        "inserir_revisao",
        inserir,
    )

    response = await http.patch(
        f"{BASE}/{d1.id}/revisao",
        json={
            "classificacao": "halitose_intima",
            "version": 0,
        },
    )

    assert response.status_code == 409
