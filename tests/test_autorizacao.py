"""Testes de RBAC: papel (403), vínculo paciente-profissional e 404 anti-enumeração.

Duas partes:

* Integração contra o Postgres do `.env` (como `test_diagnostico.py`): cria paciente,
  profissionais, admin, vínculos, anamnese, diagnóstico e imagem, e troca o usuário
  autenticado via override de `current_active_user`.
* Auth "real" (JWT + SQLite em memória, fixture `client`): usuário inativo e
  tentativa de escolher o próprio papel no cadastro.
"""

import asyncio
import logging
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import exigir_papeis
from app.api.v1.endpoints import anamnese as anamnese_endpoints
from app.api.v1.endpoints import diagnostico as diagnostico_endpoints
from app.auth import policies
from app.auth.users import current_active_user, current_active_user_opcional
from app.core.config import get_settings
from app.db import paciente_profissional_queries
from app.main import app
from app.models import (
    Anamnese,
    Diagnostico,
    Imagem,
    PacienteProfissional,
    Profissional,
    User,
)
from app.schemas.usuario import TipoUsuario
from app.services import diagnostico_storage

AUTH_HEADERS = {"Authorization": "Bearer fake-token"}


# ---------------------------------------------------------------------------
# Unidade — normalização de papel e policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "esperado"),
    [
        ("paciente", TipoUsuario.PACIENTE),
        ("patient", TipoUsuario.PACIENTE),
        (" Paciente ", TipoUsuario.PACIENTE),
        ("profissional", TipoUsuario.PROFISSIONAL),
        ("professional", TipoUsuario.PROFISSIONAL),
        ("admin", TipoUsuario.ADMIN),
        ("superuser", None),
        ("", None),
        (None, None),
    ],
)
def test_normalizar_papel(role, esperado) -> None:
    assert policies.normalizar_papel(role) is esperado


def test_policy_paciente_so_acessa_a_si_mesmo() -> None:
    paciente = SimpleNamespace(id=uuid4(), role="paciente")

    assert asyncio.run(
        policies.pode_acessar_paciente(AsyncMock(), paciente, paciente.id, recurso="teste")
    )
    assert not asyncio.run(
        policies.pode_acessar_paciente(AsyncMock(), paciente, uuid4(), recurso="teste")
    )


@pytest.mark.parametrize("tem_vinculo", [True, False])
def test_policy_profissional_depende_do_vinculo(monkeypatch, tem_vinculo: bool) -> None:
    profissional = SimpleNamespace(id=uuid4(), role="profissional")
    paciente_id = uuid4()
    consulta = AsyncMock(return_value=tem_vinculo)
    monkeypatch.setattr(paciente_profissional_queries, "profissional_tem_acesso", consulta)

    permitido = asyncio.run(
        policies.pode_acessar_paciente(AsyncMock(), profissional, paciente_id, recurso="teste")
    )

    assert permitido is tem_vinculo
    consulta.assert_awaited_once()
    assert consulta.await_args.kwargs == {
        "paciente_id": paciente_id,
        "profissional_id": profissional.id,
    }


@pytest.mark.parametrize("role", ["admin", "desconhecido"])
def test_policy_admin_e_papel_desconhecido_nao_tem_acesso_clinico(monkeypatch, role) -> None:
    consulta = AsyncMock(return_value=True)
    monkeypatch.setattr(paciente_profissional_queries, "profissional_tem_acesso", consulta)
    usuario = SimpleNamespace(id=uuid4(), role=role)

    assert not asyncio.run(
        policies.pode_acessar_paciente(AsyncMock(), usuario, usuario.id, recurso="teste")
    )
    consulta.assert_not_awaited()


# ---------------------------------------------------------------------------
# Integração — Postgres real
# ---------------------------------------------------------------------------


@dataclass
class Cenario:
    paciente: SimpleNamespace
    outro_paciente: SimpleNamespace
    profissional_vinculado: SimpleNamespace
    profissional_vinculo_inativo: SimpleNamespace
    profissional_sem_vinculo: SimpleNamespace
    admin: SimpleNamespace
    anamnese_id: int
    diagnostico_id: int
    nome_imagem: str


def _usuario(role: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), role=role, is_active=True)


def _engine():
    return create_async_engine(get_settings().database_url, poolclass=NullPool)


async def _criar_cenario() -> Cenario:
    token = uuid4().hex[:12]
    usuarios = {
        "paciente": _usuario("paciente"),
        "outro_paciente": _usuario("paciente"),
        "profissional_vinculado": _usuario("profissional"),
        # Linha antiga com alias em inglês: precisa continuar funcionando.
        "profissional_vinculo_inativo": _usuario("professional"),
        "profissional_sem_vinculo": _usuario("profissional"),
        "admin": _usuario("admin"),
    }
    nome_imagem = f"rbac-{token}.jpg"
    engine = _engine()

    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            for chave, usuario in usuarios.items():
                db.add(
                    User(
                        id=usuario.id,
                        name=f"RBAC {chave}",
                        email=f"rbac.{chave}.{token}@hality.local",
                        hashed_password="x",
                        role=usuario.role,
                    )
                )
            await db.flush()

            paciente_id = usuarios["paciente"].id
            for chave, ativo in (
                ("profissional_vinculado", True),
                ("profissional_vinculo_inativo", False),
            ):
                db.add(Profissional(usuario_id=usuarios[chave].id))
                await db.flush()
                db.add(
                    PacienteProfissional(
                        paciente_id=paciente_id,
                        profissional_id=usuarios[chave].id,
                        ativo=ativo,
                    )
                )
            # Profissional cadastrado, mas vinculado a outro paciente — nunca ao `paciente`.
            db.add(Profissional(usuario_id=usuarios["profissional_sem_vinculo"].id))
            await db.flush()
            db.add(
                PacienteProfissional(
                    paciente_id=usuarios["outro_paciente"].id,
                    profissional_id=usuarios["profissional_sem_vinculo"].id,
                )
            )

            anamnese = Anamnese(
                paciente_id=paciente_id,
                id_versao_questionario="rbac",
                respostas=[],
            )
            db.add(anamnese)
            await db.flush()

            diagnostico = Diagnostico(
                paciente_id=paciente_id,
                anamnese_id=anamnese.id,
                status="concluido",
                data_diagnostico=datetime.now(UTC),
            )
            db.add(diagnostico)
            await db.flush()

            db.add(
                Imagem(
                    diagnostico_id=diagnostico.id,
                    url_arquivo=f"/api/v1/diagnosticos/imagens/{nome_imagem}",
                    ordem=1,
                    parametros_captura={},
                )
            )
            await db.commit()

            anamnese_id, diagnostico_id = anamnese.id, diagnostico.id
    finally:
        await engine.dispose()

    diagnostico_storage._STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    (diagnostico_storage._STORAGE_DIR / nome_imagem).write_bytes(b"imagem")

    return Cenario(
        **usuarios,
        anamnese_id=anamnese_id,
        diagnostico_id=diagnostico_id,
        nome_imagem=nome_imagem,
    )


async def _remover_cenario(cenario: Cenario) -> None:
    ids = [
        cenario.paciente.id,
        cenario.outro_paciente.id,
        cenario.profissional_vinculado.id,
        cenario.profissional_vinculo_inativo.id,
        cenario.profissional_sem_vinculo.id,
        cenario.admin.id,
    ]
    engine = _engine()
    try:
        async with async_sessionmaker(engine)() as db:
            # FKs com ON DELETE CASCADE levam anamnese, diagnóstico, imagem e vínculos.
            await db.execute(delete(User).where(User.id.in_(ids)))
            await db.commit()
    finally:
        await engine.dispose()

    (diagnostico_storage._STORAGE_DIR / cenario.nome_imagem).unlink(missing_ok=True)


@pytest.fixture
def cenario() -> Iterator[Cenario]:
    criado = asyncio.run(_criar_cenario())
    try:
        yield criado
    finally:
        _deslogar()
        asyncio.run(_remover_cenario(criado))


def _autenticar_como(usuario: SimpleNamespace) -> None:
    app.dependency_overrides[current_active_user] = lambda: usuario
    app.dependency_overrides[current_active_user_opcional] = lambda: usuario


def _deslogar() -> None:
    app.dependency_overrides.pop(current_active_user, None)
    app.dependency_overrides.pop(current_active_user_opcional, None)


def _rotas_de_leitura(cenario: Cenario) -> list[str]:
    return [
        f"/api/v1/anamneses/{cenario.anamnese_id}",
        f"/api/v1/diagnosticos/{cenario.diagnostico_id}",
        f"/api/v1/diagnosticos/imagens/{cenario.nome_imagem}",
    ]


def test_paciente_dono_le_os_proprios_recursos(cenario: Cenario) -> None:
    _autenticar_como(cenario.paciente)
    client = TestClient(app)

    for rota in _rotas_de_leitura(cenario):
        assert client.get(rota, headers=AUTH_HEADERS).status_code == 200, rota


def test_profissional_com_vinculo_ativo_le_recursos_do_paciente(cenario: Cenario) -> None:
    _autenticar_como(cenario.profissional_vinculado)
    client = TestClient(app)

    for rota in _rotas_de_leitura(cenario):
        assert client.get(rota, headers=AUTH_HEADERS).status_code == 200, rota


@pytest.mark.parametrize(
    "quem", ["outro_paciente", "profissional_sem_vinculo", "profissional_vinculo_inativo"]
)
def test_sem_acesso_responde_404_igual_a_inexistente(cenario: Cenario, quem: str) -> None:
    _autenticar_como(getattr(cenario, quem))
    client = TestClient(app)
    anamnese, diagnostico, imagem = _rotas_de_leitura(cenario)

    for rota in (anamnese, imagem):
        assert client.get(rota, headers=AUTH_HEADERS).status_code == 404, rota

    # Diagnóstico mantém o contrato anterior ao RBAC: existente sem acesso -> 403.
    response = client.get(diagnostico, headers=AUTH_HEADERS)
    assert response.status_code == 403
    assert response.json() == {"detail": "diagnóstico pertence a outro paciente"}


def test_diagnostico_inexistente_continua_404(cenario: Cenario) -> None:
    _autenticar_como(cenario.paciente)

    response = TestClient(app).get("/api/v1/diagnosticos/999999999", headers=AUTH_HEADERS)

    assert response.status_code == 404


def test_admin_nao_tem_acesso_clinico_automatico(cenario: Cenario) -> None:
    _autenticar_como(cenario.admin)
    client = TestClient(app)

    for rota in [*_rotas_de_leitura(cenario), "/api/v1/diagnosticos", "/api/v1/anamneses"]:
        assert client.get(rota, headers=AUTH_HEADERS).status_code == 403, rota


@pytest.mark.parametrize("quem", ["admin", "profissional_vinculado"])
def test_nao_paciente_nao_passa_por_current_patient_dep(cenario: Cenario, quem: str) -> None:
    _autenticar_como(getattr(cenario, quem))
    client = TestClient(app)

    rotas = [
        ("GET", "/api/v1/diagnosticos", {}),
        ("GET", "/api/v1/anamneses", {}),
        ("POST", "/api/v1/anamneses", {"json": {"versao_questionario": "x", "respostas": []}}),
        (
            "POST",
            "/api/v1/diagnosticos",
            {
                "data": {"anamnese_id": str(cenario.anamnese_id), "parametros_captura": "{}"},
                "files": {"imagem": ("lingua.jpg", b"imagem", "image/jpeg")},
            },
        ),
        ("PUT", f"/api/v1/anamneses/{cenario.anamnese_id}", {"json": {}}),
        ("DELETE", f"/api/v1/anamneses/{cenario.anamnese_id}", {}),
    ]
    for metodo, rota, kwargs in rotas:
        response = client.request(metodo, rota, headers=AUTH_HEADERS, **kwargs)
        assert response.status_code == 403, (metodo, rota, response.status_code)

    # Nada foi apagado ou alterado: o dono continua lendo a anamnese.
    _autenticar_como(cenario.paciente)
    assert client.get(_rotas_de_leitura(cenario)[0], headers=AUTH_HEADERS).status_code == 200


def test_profissional_nao_usa_rotas_exclusivas_de_paciente(cenario: Cenario) -> None:
    _autenticar_como(cenario.profissional_vinculado)
    client = TestClient(app)

    # Mesmo passando o paciente_id do paciente vinculado, a listagem é só do
    # próprio paciente autenticado — profissional recebe 403.
    for rota in ("/api/v1/diagnosticos", "/api/v1/anamneses"):
        response = client.get(
            rota, params={"paciente_id": str(cenario.paciente.id)}, headers=AUTH_HEADERS
        )
        assert response.status_code == 403, rota

    response = client.delete(f"/api/v1/anamneses/{cenario.anamnese_id}", headers=AUTH_HEADERS)
    assert response.status_code == 403


def test_query_de_vinculo_so_considera_vinculo_ativo(cenario: Cenario) -> None:
    async def consultar(paciente_id: uuid.UUID, profissional_id: uuid.UUID) -> bool:
        engine = _engine()
        try:
            async with AsyncSession(engine) as db:
                return await paciente_profissional_queries.profissional_tem_acesso(
                    db, paciente_id=paciente_id, profissional_id=profissional_id
                )
        finally:
            await engine.dispose()

    paciente_id = cenario.paciente.id
    vinculado = cenario.profissional_vinculado.id

    assert asyncio.run(consultar(paciente_id, vinculado))
    assert not asyncio.run(consultar(paciente_id, cenario.profissional_vinculo_inativo.id))
    assert not asyncio.run(consultar(cenario.outro_paciente.id, vinculado))


# ---------------------------------------------------------------------------
# Auth real (JWT + SQLite) — inativo e papel escolhido pelo cliente
# ---------------------------------------------------------------------------

_USUARIO = {
    "email": "rbac@hality.com",
    "password": "SenhaSegura123!",
    "name": "Usuário RBAC",
}


async def _login(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": _USUARIO["email"], "password": _USUARIO["password"]},
    )
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_cadastro_ignora_role_enviado_pelo_cliente(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/register", json={**_USUARIO, "role": "admin"})

    assert response.status_code == 201
    assert response.json()["role"] == TipoUsuario.PACIENTE


@pytest.mark.asyncio
async def test_usuario_inativo_recebe_401_antes_da_regra_de_recurso(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.post("/api/v1/auth/register", json=_USUARIO)
    access_token = await _login(client)

    await db_session.execute(
        update(User).where(User.email == _USUARIO["email"]).values(is_active=False)
    )
    await db_session.commit()

    response = await client.get(
        "/api/v1/diagnosticos/1", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Chamada direta à API (sem UI) — auth real, sem override
# ---------------------------------------------------------------------------

_ROTAS_CLINICAS = [
    ("GET", "/api/v1/anamneses"),
    ("POST", "/api/v1/anamneses"),
    ("GET", "/api/v1/anamneses/1"),
    ("PUT", "/api/v1/anamneses/1"),
    ("DELETE", "/api/v1/anamneses/1"),
    ("GET", "/api/v1/diagnosticos"),
    ("POST", "/api/v1/diagnosticos"),
    ("GET", "/api/v1/diagnosticos/1"),
    ("GET", "/api/v1/diagnosticos/imagens/qualquer.jpg"),
]


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer token-forjado"}, {"Authorization": "Basic abc"}],
    ids=["sem-token", "token-invalido", "esquema-errado"],
)
def test_chamada_direta_sem_credencial_valida_recebe_401(headers: dict) -> None:
    assert current_active_user not in app.dependency_overrides
    assert current_active_user_opcional not in app.dependency_overrides
    client = TestClient(app)

    for metodo, rota in _ROTAS_CLINICAS:
        response = client.request(metodo, rota, headers=headers)
        assert response.status_code == 401, (metodo, rota, response.status_code)


def test_chamada_direta_com_ids_forjados_nao_eleva_acesso(cenario: Cenario) -> None:
    """Cliente que monta a request na mão, passando ids de outro paciente."""
    _autenticar_como(cenario.outro_paciente)
    client = TestClient(app)
    alvo = str(cenario.paciente.id)

    listagem = client.get("/api/v1/anamneses", params={"paciente_id": alvo}, headers=AUTH_HEADERS)
    assert listagem.status_code == 200
    assert cenario.anamnese_id not in {item["id"] for item in listagem.json()}

    diagnosticos = client.get(
        "/api/v1/diagnosticos", params={"paciente_id": alvo}, headers=AUTH_HEADERS
    )
    assert diagnosticos.status_code == 200
    assert cenario.diagnostico_id not in {item["id"] for item in diagnosticos.json()["itens"]}

    # Criar diagnóstico em cima da anamnese de outro paciente: 404, sem gravar nada.
    criacao = client.post(
        "/api/v1/diagnosticos",
        data={
            "anamnese_id": str(cenario.anamnese_id),
            "parametros_captura": "{}",
            "paciente_id": alvo,
        },
        files={"imagem": ("lingua.jpg", b"imagem", "image/jpeg")},
        headers=AUTH_HEADERS,
    )
    assert criacao.status_code == 404

    # `role` no header/query não muda o papel do usuário autenticado.
    _autenticar_como(cenario.admin)
    response = client.get(
        _rotas_de_leitura(cenario)[1],
        params={"role": "paciente"},
        headers={**AUTH_HEADERS, "X-Role": "profissional"},
    )
    assert response.status_code == 403


def test_detalhe_so_conta_vinculo_ativo_em_tem_profissional_vinculado(cenario: Cenario) -> None:
    rota = f"/api/v1/diagnosticos/{cenario.diagnostico_id}"
    _autenticar_como(cenario.paciente)
    client = TestClient(app)

    assert client.get(rota, headers=AUTH_HEADERS).json()["tem_profissional_vinculado"] is True

    async def desativar_vinculos() -> None:
        engine = _engine()
        try:
            async with AsyncSession(engine) as db:
                await db.execute(
                    update(PacienteProfissional)
                    .where(PacienteProfissional.paciente_id == cenario.paciente.id)
                    .values(ativo=False)
                )
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(desativar_vinculos())

    assert client.get(rota, headers=AUTH_HEADERS).json()["tem_profissional_vinculado"] is False


# ---------------------------------------------------------------------------
# Observabilidade — decisão, recurso e correlation id, sem payload
# ---------------------------------------------------------------------------


def _registros_authz(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.authz"]


def test_log_de_negacao_por_papel_tem_recurso_e_correlation_id(
    cenario: Cenario, caplog: pytest.LogCaptureFixture
) -> None:
    _autenticar_como(cenario.admin)
    client = TestClient(app)
    caplog.set_level(logging.INFO, logger="app.authz")

    response = client.get(
        "/api/v1/diagnosticos",
        params={"paciente_id": "segredo-na-query"},
        headers={**AUTH_HEADERS, "X-Correlation-ID": "req-123"},
    )

    assert response.status_code == 403
    (registro,) = _registros_authz(caplog)
    assert registro.levelno == logging.WARNING
    assert registro.authz_decisao == "negado"
    assert registro.authz_motivo == "papel_insuficiente"
    assert registro.authz_recurso == "GET /api/v1/diagnosticos"
    assert registro.usuario_id == str(cenario.admin.id)
    assert registro.papel == "admin"
    assert registro.correlation_id == "req-123"
    assert "segredo-na-query" not in registro.getMessage()


def test_log_de_decisao_de_recurso_nao_inclui_payload(
    cenario: Cenario, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.authz")
    client = TestClient(app)

    _autenticar_como(cenario.profissional_vinculado)
    client.get(f"/api/v1/diagnosticos/{cenario.diagnostico_id}", headers=AUTH_HEADERS)
    _autenticar_como(cenario.outro_paciente)
    client.put(
        f"/api/v1/anamneses/{cenario.anamnese_id}",
        json={
            "versao_questionario": "x",
            "respostas": [{"pergunta_id": "q1", "valor": "dado-clinico-sensivel"}],
        },
        headers=AUTH_HEADERS,
    )

    permitido, negado = _registros_authz(caplog)
    assert (permitido.authz_decisao, permitido.authz_motivo) == ("permitido", "vinculo_ativo")
    assert permitido.authz_recurso == f"diagnostico:{cenario.diagnostico_id}"
    assert (negado.authz_decisao, negado.authz_motivo) == ("negado", "nao_e_dono")
    assert negado.authz_recurso == f"anamnese:{cenario.anamnese_id}"
    # O id definido em `exigir_papeis` chega à decisão tomada dentro do service,
    # e cada request recebe o seu.
    assert all(re.fullmatch(r"[0-9a-f]{32}", r.correlation_id) for r in (permitido, negado))
    assert permitido.correlation_id != negado.correlation_id
    assert "dado-clinico-sensivel" not in caplog.text


def test_correlation_id_invalido_do_cliente_e_substituido(
    cenario: Cenario, caplog: pytest.LogCaptureFixture
) -> None:
    _autenticar_como(cenario.admin)
    caplog.set_level(logging.INFO, logger="app.authz")

    TestClient(app).get(
        "/api/v1/diagnosticos",
        headers={**AUTH_HEADERS, "X-Correlation-ID": "x forjado=1;" + "a" * 200},
    )

    (registro,) = _registros_authz(caplog)
    assert re.fullmatch(r"[0-9a-f]{32}", registro.correlation_id)
    assert "forjado" not in registro.getMessage()


# ---------------------------------------------------------------------------
# Arquitetura — uma única camada de autorização
# ---------------------------------------------------------------------------

_APP_DIR = Path(__file__).resolve().parents[1] / "app"
# Routers de recursos clínicos. Router clínico novo deve entrar nesta lista.
_ROUTERS_CLINICOS = (anamnese_endpoints.router, diagnostico_endpoints.router)
_ROTAS_CLINICAS_PUBLICAS = {"/anamneses/questionario"}


def _papeis_declarados(dependant: Dependant) -> list[frozenset]:
    encontrados = []
    for sub in dependant.dependencies:
        papeis = getattr(sub.call, "papeis_permitidos", None)
        if papeis is not None:
            encontrados.append(papeis)
        encontrados.extend(_papeis_declarados(sub))
    return encontrados


def test_toda_rota_clinica_declara_papeis_via_exigir_papeis() -> None:
    rotas = [
        r
        for router in _ROUTERS_CLINICOS
        for r in router.routes
        if isinstance(r, APIRoute) and r.path not in _ROTAS_CLINICAS_PUBLICAS
    ]
    assert len(rotas) == 9

    for rota in rotas:
        papeis = _papeis_declarados(rota.dependant)
        assert len(papeis) == 1, f"{rota.methods} {rota.path}: {papeis}"
        assert TipoUsuario.ADMIN not in papeis[0], f"{rota.path} liberou admin sem declarar"


def test_nenhum_modulo_checa_papel_ou_dono_fora_da_camada_de_autorizacao() -> None:
    """Checagem de papel só em `deps.py`/`policies.py`; comparação de dono só na policy.

    `home_service.py` só exibe o papel (tipo_usuario), não decide nada com ele.
    Filtros SQL (`where(...)`, módulos em `db/` e o repositório) não são decisão
    de acesso — só restringem a consulta ao id que a policy já validou.
    """
    permitidos_role = {
        "auth/policies.py",
        # Código da #88 (vínculo), mantido como veio da develop:
        # `get_current_professional` e a validação do e-mail em `criar_vinculo`.
        "api/deps.py",
        "services/vinculo_service.py",
        "models/user.py",
        "services/home_service.py",
        # Gestão de contas (#96): `role` é o dado administrado (filtro, payload,
        # troca de papel), não decisão de acesso — que continua em `require_admin`.
        "services/admin_usuario_service.py",
        "db/user_queries.py",
        "schemas/admin_usuario.py",
    }
    permitidos_dono = {"auth/policies.py", "services/anamnese_store.py"}
    padrao_role = re.compile(r"\.role\b|\bis_superuser\b")
    padrao_comparacao = re.compile(r"[!=]=")
    violacoes = []

    for arquivo in _APP_DIR.rglob("*.py"):
        relativo = arquivo.relative_to(_APP_DIR).as_posix()
        for numero, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), 1):
            codigo = linha.split("#", 1)[0]
            if padrao_role.search(codigo) and relativo not in permitidos_role:
                violacoes.append(f"{relativo}:{numero}: {linha.strip()}")
            # Comparar paciente_id fora de filtro SQL = checagem de dono paralela.
            if (
                "paciente_id" in codigo
                and padrao_comparacao.search(codigo)
                and "where(" not in codigo
                and not relativo.startswith("db/")
                and relativo not in permitidos_dono
            ):
                violacoes.append(f"{relativo}:{numero}: {linha.strip()}")

    assert not violacoes, "autorização fora de app/auth/policies.py:\n" + "\n".join(violacoes)


def test_exigir_papeis_expoe_papeis_para_auditoria() -> None:
    dependencia = exigir_papeis(TipoUsuario.PACIENTE, TipoUsuario.PROFISSIONAL)
    assert dependencia.papeis_permitidos == {TipoUsuario.PACIENTE, TipoUsuario.PROFISSIONAL}


# ---------------------------------------------------------------------------
# Imagem por URL assinada — o front usa `url_arquivo` direto em <img>
# ---------------------------------------------------------------------------


def _url_da_imagem_no_detalhe(cenario: Cenario, usuario: SimpleNamespace) -> str:
    _autenticar_como(usuario)
    response = TestClient(app).get(
        f"/api/v1/diagnosticos/{cenario.diagnostico_id}", headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    return response.json()["imagens"][0]["url_arquivo"]


@pytest.mark.parametrize("quem", ["paciente", "profissional_vinculado"])
def test_url_da_imagem_no_detalhe_abre_sem_bearer(cenario: Cenario, quem: str) -> None:
    url = _url_da_imagem_no_detalhe(cenario, getattr(cenario, quem))
    _deslogar()

    # Igual ao <img src> do front: sem header Authorization nenhum.
    response = TestClient(app).get(url)

    assert url.startswith(f"/api/v1/diagnosticos/imagens/{cenario.nome_imagem}?expira=")
    assert response.status_code == 200
    assert response.content == b"imagem"


def test_url_assinada_adulterada_ou_de_outro_arquivo_responde_404(cenario: Cenario) -> None:
    url = _url_da_imagem_no_detalhe(cenario, cenario.paciente)
    _deslogar()
    client = TestClient(app)

    adulterada = url[:-1] + ("0" if url[-1] != "0" else "1")
    outro_arquivo = url.replace(cenario.nome_imagem, "outro-arquivo.jpg")
    sem_assinatura = url.split("?", 1)[0]

    assert client.get(adulterada).status_code == 404
    assert client.get(outro_arquivo).status_code == 404
    # Sem Bearer e sem assinatura: mesma resposta de antes para a rota (401).
    assert client.get(sem_assinatura).status_code == 401


def test_url_assinada_expirada_responde_404(cenario: Cenario) -> None:
    url = policies.assinar_url_imagem(
        f"/api/v1/diagnosticos/imagens/{cenario.nome_imagem}", validade_segundos=-1
    )

    assert TestClient(app).get(url).status_code == 404


def test_rota_da_imagem_com_bearer_continua_protegida(cenario: Cenario) -> None:
    rota = f"/api/v1/diagnosticos/imagens/{cenario.nome_imagem}"

    _autenticar_como(cenario.outro_paciente)
    assert TestClient(app).get(rota, headers=AUTH_HEADERS).status_code == 404

    _deslogar()
    assert TestClient(app).get(rota).status_code == 401


def test_log_do_acesso_por_url_assinada(cenario: Cenario, caplog: pytest.LogCaptureFixture) -> None:
    url = _url_da_imagem_no_detalhe(cenario, cenario.paciente)
    _deslogar()
    caplog.set_level(logging.INFO, logger="app.authz")

    TestClient(app).get(url)

    (registro,) = _registros_authz(caplog)
    assert (registro.authz_decisao, registro.authz_motivo) == ("permitido", "url_assinada")
    assert registro.authz_recurso == f"imagem:{cenario.nome_imagem}"
    assert registro.usuario_id == "anonimo"
    assert "assinatura" not in registro.getMessage()
