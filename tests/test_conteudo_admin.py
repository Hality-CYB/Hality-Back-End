"""Integração do catálogo estruturado de conteúdos administrativos (TASK-101)."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.users import current_active_user
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models import ClassificacaoDiagnostico, Conteudo
from app.schemas.conteudo import ConteudoListResponse
from tests.conftest import CenarioAdmin, autenticar_como

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/admin/conteudos"
AUTH_HEADERS = {"Authorization": "Bearer fake-token"}
PAYLOAD = {
    "titulo": "Higiene bucal",
    "categoria": "tratamento",
    "conteudo": {
        "itens": [
            {"tipo": "texto", "texto": "Use fio dental.", "origem": "editorial"},
            {"tipo": "checklist", "itens": ["Escovar", "Enxaguar"]},
        ]
    },
    "classificacao_ids": [],
    "aparece_na_home": True,
    "status": "rascunho",
    "ordem": 1,
}


@pytest_asyncio.fixture
async def db_factory(cenario_admin: CenarioAdmin) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield factory
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


@pytest_asyncio.fixture
async def http(db_factory) -> AsyncGenerator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture(autouse=True)
async def limpar_conteudos_da_task(db_factory, cenario_admin: CenarioAdmin) -> AsyncGenerator[None]:
    yield

    async with db_factory() as db:
        await db.execute(delete(Conteudo).where(Conteudo.criado_por_id == cenario_admin.admin.id))
        await db.commit()


@pytest_asyncio.fixture
async def conteudos(
    db_factory, cenario_admin: CenarioAdmin
) -> AsyncGenerator[list[Conteudo]]:
    async with db_factory() as db:
        classificacoes = list(
            (
                await db.scalars(
                    select(ClassificacaoDiagnostico)
                    .order_by(ClassificacaoDiagnostico.id)
                    .limit(2)
                )
            ).all()
        )
        agora = datetime(2026, 10, 1, 12, tzinfo=UTC)
        registros = [
            Conteudo(
                titulo="Higiene bucal",
                categoria="tratamento",
                conteudo={"itens": [{"tipo": "texto", "texto": "higiene", "extra": 1}]},
                classificacao_ids=[classificacoes[0].id],
                aparece_na_home=True,
                status="publicado",
                ordem=1,
                created_at=agora,
                updated_at=agora,
                criado_por_id=cenario_admin.admin.id,
                atualizado_por_id=cenario_admin.admin.id,
                publicado_por_id=cenario_admin.admin.id,
                publicado_em=agora,
            ),
            Conteudo(
                titulo="Rotina diária",
                categoria="higiene",
                conteudo={"itens": [{"tipo": "imagem", "url": "/rotina.png"}]},
                classificacao_ids=[classificacoes[1].id],
                aparece_na_home=False,
                status="rascunho",
                ordem=1,
                created_at=agora,
                updated_at=agora,
                criado_por_id=cenario_admin.admin.id,
                atualizado_por_id=cenario_admin.admin.id,
            ),
            Conteudo(
                titulo="Escovacao avancada",
                categoria="tratamento",
                conteudo={"itens": [{"tipo": "checklist", "itens": ["escovacao"]}]},
                classificacao_ids=[classificacoes[0].id, classificacoes[1].id],
                aparece_na_home=True,
                status="publicado",
                ordem=2,
                created_at=agora,
                updated_at=agora,
                criado_por_id=cenario_admin.admin.id,
                atualizado_por_id=cenario_admin.admin.id,
                publicado_por_id=cenario_admin.admin.id,
                publicado_em=agora,
            ),
        ]
        db.add_all(registros)
        await db.commit()
        yield registros


def _autenticar(http: AsyncClient, usuario) -> None:
    autenticar_como(usuario)
    http.headers.update(AUTH_HEADERS)


@pytest.mark.parametrize(
    ("method", "usa_detalhe"),
    [("post", False), ("get", False), ("get", True), ("put", True), ("patch", True), ("delete", True)],
)
async def test_todas_rotas_exigem_autenticacao(http, method, usa_detalhe, conteudos):
    path = f"{BASE}/{conteudos[0].id}" if usa_detalhe else BASE
    kwargs = {"json": PAYLOAD} if method in {"post", "put", "patch"} else {}
    response = await getattr(http, method)(path, **kwargs)
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "usa_detalhe"),
    [("post", False), ("get", False), ("get", True), ("put", True), ("patch", True), ("delete", True)],
)
async def test_todas_rotas_rejeitam_usuario_nao_admin(
    http, method, usa_detalhe, conteudos, cenario_admin
):
    _autenticar(http, cenario_admin.paciente)
    path = f"{BASE}/{conteudos[0].id}" if usa_detalhe else BASE
    kwargs = {"json": PAYLOAD} if method in {"post", "put", "patch"} else {}
    response = await getattr(http, method)(path, **kwargs)
    assert response.status_code == 403


async def test_admin_autenticado_trata_inexistente_e_delete(http, cenario_admin):
    _autenticar(http, cenario_admin.admin)
    inexistente = 2147483647
    assert (await http.get(f"{BASE}/{inexistente}")).status_code == 404
    assert (await http.patch(f"{BASE}/{inexistente}", json={"ordem": 2})).status_code == 404
    assert (await http.put(f"{BASE}/{inexistente}", json=PAYLOAD)).status_code == 404
    assert (await http.delete(f"{BASE}/{inexistente}")).status_code == 404

    criado = await http.post(BASE, json=PAYLOAD)
    assert criado.status_code == 201
    conteudo_id = criado.json()["id"]
    assert (await http.delete(f"{BASE}/{conteudo_id}")).status_code == 204
    assert (await http.get(f"{BASE}/{conteudo_id}")).status_code == 404


async def test_filtros_combinados_e_id_inexistente(http, conteudos, cenario_admin):
    _autenticar(http, cenario_admin.admin)
    classificacao_id = conteudos[0].classificacao_ids[0]
    filtros_isolados = [
        ({"status": "publicado"}, {conteudos[0].id, conteudos[2].id}),
        ({"categoria": "tratamento"}, {conteudos[0].id, conteudos[2].id}),
        ({"classificacao_id": classificacao_id}, {conteudos[0].id, conteudos[2].id}),
        ({"q": "escovacao"}, {conteudos[2].id}),
        ({"aparece_na_home": True}, {conteudos[0].id, conteudos[2].id}),
    ]
    for params, ids_esperados in filtros_isolados:
        resposta_isolada = await http.get(BASE, params=params)
        assert resposta_isolada.status_code == 200
        assert {item["id"] for item in resposta_isolada.json()["items"]} == ids_esperados

    response = await http.get(
        BASE,
        params={
            "status": "publicado",
            "categoria": "tratamento",
            "classificacao_id": classificacao_id,
            "q": "escovacao",
            "aparece_na_home": True,
        },
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [conteudos[2].id]
    assert (await http.get(BASE, params={"classificacao_id": 999999})).json()["items"] == []


async def test_paginacao_ordenacao_estavel_e_pagina_alem_do_total(http, conteudos, cenario_admin):
    _autenticar(http, cenario_admin.admin)
    ids = [registro.id for registro in conteudos]
    ordens_esperadas = {
        "ordem_asc": ids,
        "ordem_desc": [ids[2], ids[1], ids[0]],
        "created_at_asc": ids,
        "created_at_desc": ids,
    }
    for order, esperado in ordens_esperadas.items():
        paginas = [
            (await http.get(BASE, params={"order": order, "page": pagina, "limit": 1})).json()
            for pagina in (1, 2, 3)
        ]
        repetida = (await http.get(BASE, params={"order": order, "page": 1, "limit": 1})).json()
        assert [pagina["items"][0]["id"] for pagina in paginas] == esperado
        assert paginas[0]["items"] == repetida["items"]
        assert paginas[0]["total"] == 3
        assert paginas[0]["has_next"] is True
        assert paginas[-1]["has_next"] is False
        assert {item["id"] for pagina in paginas for item in pagina["items"]} == set(ids)
    ultima = (await http.get(BASE, params={"page": 2, "limit": 2})).json()
    alem = (await http.get(BASE, params={"page": 3, "limit": 2})).json()
    assert len(ultima["items"]) == 1 and ultima["has_next"] is False
    assert alem["items"] == [] and alem["total"] == 3 and alem["has_next"] is False


async def test_busca_por_titulo_acento_case_e_wildcards(http, conteudos, cenario_admin):
    _autenticar(http, cenario_admin.admin)
    casos = [
        ("HIGIENE", {conteudos[0].id}),
        ("DIÁRIA", {conteudos[1].id}),
        ("%", set()),
        ("_", set()),
        ("tipo", set()),
    ]
    for busca, ids_esperados in casos:
        resposta = await http.get(BASE, params={"q": busca})
        assert resposta.status_code == 200
        assert {item["id"] for item in resposta.json()["items"]} == ids_esperados


@pytest.mark.parametrize(
    "params",
    [
        {"status": "inexistente"},
        {"categoria": "inexistente"},
        {"limit": 0},
        {"limit": 51},
        {"page": 0},
        {"classificacao_id": 0},
    ],
)
async def test_filtros_invalidos_retornam_422(http, params, cenario_admin):
    _autenticar(http, cenario_admin.admin)
    assert (await http.get(BASE, params=params)).status_code == 422


async def test_busca_vazia_e_contrato_da_resposta_real(http, conteudos, cenario_admin):
    _autenticar(http, cenario_admin.admin)
    resposta = await http.get(BASE, params={"q": "   "})
    assert resposta.status_code == 200
    contrato = ConteudoListResponse.model_validate(resposta.json())
    assert contrato.items[0].conteudo.itens


async def test_openapi_documenta_filtros_e_limites():
    openapi = app.openapi()
    operacao = openapi["paths"][BASE]["get"]
    parametros = {parametro["name"]: parametro for parametro in operacao["parameters"]}

    def resolver(schema):
        if "$ref" in schema:
            return openapi["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
        if "anyOf" in schema:
            return resolver(next(item for item in schema["anyOf"] if item.get("type") != "null"))
        return schema

    assert resolver(parametros["order"]["schema"])["enum"] == [
        "ordem_asc",
        "ordem_desc",
        "created_at_asc",
        "created_at_desc",
    ]
    assert resolver(parametros["status"]["schema"])["enum"] == ["rascunho", "publicado"]
    assert parametros["page"]["schema"]["minimum"] == 1
    assert parametros["limit"]["schema"]["minimum"] == 1
    assert parametros["limit"]["schema"]["maximum"] == 50
    assert resolver(parametros["q"]["schema"])["maxLength"] == 100


async def test_escrita_preserva_json_e_publicacao(http, cenario_admin):
    _autenticar(http, cenario_admin.admin)
    criado = await http.post(BASE, json=PAYLOAD)
    assert criado.status_code == 201
    conteudo_id = criado.json()["id"]
    esperado = PAYLOAD["conteudo"]
    assert (await http.get(f"{BASE}/{conteudo_id}")).json()["conteudo"] == esperado
    atualizado = {"conteudo": {"itens": [{"tipo": "card", "titulo": "Extra", "ativo": True}]}}
    assert (await http.patch(f"{BASE}/{conteudo_id}", json=atualizado)).status_code == 200
    assert (await http.get(f"{BASE}/{conteudo_id}")).json()["conteudo"] == atualizado["conteudo"]
    assert (await http.patch(f"{BASE}/{conteudo_id}", json={"status": "publicado"})).status_code == 200
    publicado = (await http.get(f"{BASE}/{conteudo_id}")).json()
    assert publicado["publicado_por_id"] == str(cenario_admin.admin.id)
    publicado_em = publicado["publicado_em"]
    assert (await http.patch(f"{BASE}/{conteudo_id}", json={"status": "publicado"})).status_code == 200
    assert (await http.get(f"{BASE}/{conteudo_id}")).json()["publicado_em"] == publicado_em
    assert (await http.patch(f"{BASE}/{conteudo_id}", json={"status": "rascunho"})).status_code == 200
    rascunho = (await http.get(f"{BASE}/{conteudo_id}")).json()
    assert rascunho["publicado_por_id"] is None and rascunho["publicado_em"] is None


async def test_erros_de_escrita_e_null_explicito(http, cenario_admin):
    _autenticar(http, cenario_admin.admin)
    payload = {**PAYLOAD, "classificacao_ids": [999999]}
    assert (await http.post(BASE, json=payload)).status_code == 400
    assert (await http.post(BASE, json=PAYLOAD)).status_code == 201
    conteudo_id = (await http.post(BASE, json=PAYLOAD)).json()["id"]
    assert (await http.patch(f"{BASE}/{conteudo_id}", json={"conteudo": None})).status_code == 422


async def test_fluxo_nao_depende_de_dicas(http, cenario_admin):
    _autenticar(http, cenario_admin.admin)
    criado = await http.post(BASE, json=PAYLOAD)
    assert criado.status_code == 201
    conteudo_id = criado.json()["id"]
    assert (await http.get(BASE)).status_code == 200
    assert (await http.get(BASE, params={"status": "rascunho"})).status_code == 200
    assert (await http.patch(f"{BASE}/{conteudo_id}", json={"ordem": 9})).status_code == 200
    assert (await http.get(f"{BASE}/{conteudo_id}")).status_code == 200
    assert "/api/v1/dicas" not in app.openapi().get("paths", {})