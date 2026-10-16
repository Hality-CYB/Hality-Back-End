from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models import Conteudo
from tests.conftest import CenarioAdmin, autenticar_como

pytestmark = pytest.mark.asyncio

CAPTURA_URL = "/api/v1/conteudos/captura"
LANDING_URL = "/api/v1/public/landing"
AUTH_HEADERS = {"Authorization": "Bearer fake-token"}


@pytest_asyncio.fixture
async def db_factory(
    cenario_admin: CenarioAdmin,
) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
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


@pytest_asyncio.fixture
async def conteudos_publicos(
    db_factory,
    cenario_admin: CenarioAdmin,
) -> AsyncGenerator[list[Conteudo]]:
    agora = datetime(2026, 10, 1, 12, tzinfo=UTC)

    registros = [
        Conteudo(
            titulo="Orientação para captura",
            categoria="higiene",
            conteudo={"itens": [{"tipo": "texto", "texto": "Posicione a língua corretamente."}]},
            classificacao_ids=[],
            destinos=["captura"],
            aparece_na_home=False,
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
            titulo="Captura em rascunho",
            categoria="higiene",
            conteudo={"itens": [{"tipo": "texto", "texto": "Não deve aparecer."}]},
            classificacao_ids=[],
            destinos=["captura"],
            aparece_na_home=False,
            status="rascunho",
            ordem=2,
            created_at=agora,
            updated_at=agora,
            criado_por_id=cenario_admin.admin.id,
            atualizado_por_id=cenario_admin.admin.id,
        ),
        Conteudo(
            titulo="Conheça a Hality",
            categoria="saude",
            conteudo={
                "itens": [
                    {"tipo": "texto", "texto": "Informação pública."},
                    {"tipo": "imagem", "url": "/hality.png", "alt": "Hality"},
                ]
            },
            classificacao_ids=[],
            destinos=["landing_publica"],
            aparece_na_home=False,
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
            titulo="Landing em rascunho",
            categoria="saude",
            conteudo={"itens": [{"tipo": "texto", "texto": "Não deve aparecer."}]},
            classificacao_ids=[],
            destinos=["landing_publica"],
            aparece_na_home=False,
            status="rascunho",
            ordem=2,
            created_at=agora,
            updated_at=agora,
            criado_por_id=cenario_admin.admin.id,
            atualizado_por_id=cenario_admin.admin.id,
        ),
    ]

    async with db_factory() as db:
        db.add_all(registros)
        await db.commit()

    yield registros

    async with db_factory() as db:
        await db.execute(delete(Conteudo).where(Conteudo.id.in_([item.id for item in registros])))
        await db.commit()


async def test_captura_exige_autenticacao(http, conteudos_publicos):
    response = await http.get(CAPTURA_URL)
    assert response.status_code == 401


@pytest.mark.parametrize("usuario", ["paciente", "profissional"])
async def test_captura_permite_paciente_e_profissional(
    http,
    conteudos_publicos,
    cenario_admin,
    usuario,
):
    autenticar_como(getattr(cenario_admin, usuario))
    response = await http.get(CAPTURA_URL, headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert [item["titulo"] for item in response.json()] == ["Orientação para captura"]


async def test_captura_rejeita_admin(http, conteudos_publicos, cenario_admin):
    autenticar_como(cenario_admin.admin)
    response = await http.get(CAPTURA_URL, headers=AUTH_HEADERS)
    assert response.status_code == 403


async def test_landing_e_publica_e_retorna_somente_publicados(http, conteudos_publicos):
    response = await http.get(LANDING_URL)

    assert response.status_code == 200
    assert [item["titulo"] for item in response.json()] == ["Conheça a Hality"]
    assert response.headers["cache-control"] == "public, max-age=300"


async def test_landing_nao_expoe_campos_internos(http, conteudos_publicos):
    response = await http.get(LANDING_URL)
    item = response.json()[0]

    assert set(item) == {"id", "titulo", "categoria", "conteudo", "ordem"}
    assert "classificacao_ids" not in item
    assert "destinos" not in item
    assert "aparece_na_home" not in item
    assert "status" not in item
    assert "criado_por_id" not in item
    assert "publicado_por_id" not in item


async def test_landing_rejeita_url_invalida_alt_ausente_e_html(http, cenario_admin):
    autenticar_como(cenario_admin.admin)

    base = {
        "titulo": "Landing",
        "categoria": "saude",
        "classificacao_ids": [],
        "destinos": ["landing_publica"],
        "aparece_na_home": False,
        "status": "rascunho",
        "ordem": 1,
    }

    payloads = [
        {
            **base,
            "conteudo": {
                "itens": [
                    {"tipo": "imagem", "url": "javascript:alert(1)", "alt": "Imagem"},
                ]
            },
        },
        {
            **base,
            "conteudo": {
                "itens": [
                    {"tipo": "imagem", "url": "/imagem.png"},
                ]
            },
        },
        {
            **base,
            "conteudo": {
                "itens": [
                    {"tipo": "texto", "texto": "<script>alert(1)</script>"},
                ]
            },
        },
    ]

    for payload in payloads:
        response = await http.post(
            "/api/v1/admin/conteudos",
            json=payload,
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422
