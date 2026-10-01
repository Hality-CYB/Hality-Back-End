"""US-090 — profissional registrando anamnese/diagnóstico para paciente vinculado.

Três blocos:

* **Service (sem banco)** — `criar_diagnostico` com queries/storage mockados:
  vínculo e executor checados antes do storage, retry idempotente e limpeza de
  arquivo órfão.
* **HTTP (sem banco)** — papel (403), sem acesso (404, convenção do #92) e o
  contrato do 409.
* **Integração (Postgres real do `.env`)** — fluxo ponta a ponta do
  profissional, conferindo `paciente_id`/`executor_id` gravados.

A regra de acesso é a de `app/auth/policies.py` (`pode_acessar_paciente`); aqui
só o vínculo (`profissional_tem_acesso`) é mockado.
"""

import asyncio
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import policies
from app.auth.users import current_active_user
from app.core.config import get_settings
from app.main import app
from app.models import (
    Anamnese,
    Diagnostico,
    Imagem,
    PacienteProfissional,
    Profissional,
    User,
)
from app.services import anamnese_questionary, anamnese_service, diagnostico_service

AUTH_HEADERS = {"Authorization": "Bearer fake-token"}
PROFISSIONAL_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
PACIENTE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
OUTRO_PACIENTE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b2")

PROFISSIONAL = SimpleNamespace(id=PROFISSIONAL_ID, role="profissional")
PACIENTE = SimpleNamespace(id=PACIENTE_ID, role="paciente")

URL_IMAGEM = "/api/v1/diagnosticos/imagens/teste.jpg"

client = TestClient(app)


def _anamnese(paciente_id=PACIENTE_ID, executor_id=PROFISSIONAL_ID):
    return SimpleNamespace(
        id=128,
        paciente_id=paciente_id,
        executor_id=executor_id,
        data_preenchimento=datetime.now(UTC),
        respostas=[],
    )


def _diagnostico(paciente_id=PACIENTE_ID, executor_id=PROFISSIONAL_ID):
    return SimpleNamespace(
        id=4,
        paciente_id=paciente_id,
        executor_id=executor_id,
        anamnese_id=128,
        status="processando",
        data_diagnostico=datetime.now(UTC),
    )


@pytest.fixture
def mocks(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Queries, vínculo e storage do fluxo de criação, todos mockados."""
    m = SimpleNamespace(
        buscar_anamnese=AsyncMock(return_value=_anamnese()),
        buscar_por_anamnese=AsyncMock(return_value=None),
        inserir=AsyncMock(return_value=_diagnostico()),
        salvar=AsyncMock(return_value=URL_IMAGEM),
        remover=AsyncMock(),
        tem_vinculo=AsyncMock(return_value=True),
        buscar_usuario=AsyncMock(return_value=SimpleNamespace(id=PACIENTE_ID, is_active=True)),
    )
    monkeypatch.setattr(diagnostico_service.anamnese_queries, "buscar_por_id", m.buscar_anamnese)
    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries, "buscar_por_anamnese", m.buscar_por_anamnese
    )
    monkeypatch.setattr(diagnostico_service.diagnostico_queries, "inserir", m.inserir)
    monkeypatch.setattr(diagnostico_service.diagnostico_storage, "salvar", m.salvar)
    monkeypatch.setattr(diagnostico_service.diagnostico_storage, "remover", m.remover)
    monkeypatch.setattr(
        policies.paciente_profissional_queries, "profissional_tem_acesso", m.tem_vinculo
    )
    monkeypatch.setattr(anamnese_service.user_queries, "buscar_usuario", m.buscar_usuario)
    monkeypatch.setattr(
        diagnostico_service,
        "get_settings",
        lambda: SimpleNamespace(api_v1_prefix="/api/v1"),
    )
    return m


def _criar(usuario: SimpleNamespace, db=None):
    return asyncio.run(
        diagnostico_service.criar_diagnostico(
            db=db or AsyncMock(),
            usuario=usuario,
            anamnese_id=128,
            imagem=b"imagem",
            content_type="image/jpeg",
            parametros_captura={"flash": True},
        )
    )


# ---------------------------------------------------------------------------
# Service — sem banco
# ---------------------------------------------------------------------------


def test_paciente_continua_criando_para_si(mocks: SimpleNamespace) -> None:
    mocks.buscar_anamnese.return_value = _anamnese(executor_id=PACIENTE_ID)

    _criar(PACIENTE)

    kwargs = mocks.inserir.await_args.kwargs
    assert (kwargs["paciente_id"], kwargs["executor_id"]) == (PACIENTE_ID, PACIENTE_ID)


def test_paciente_usa_anamnese_legada_sem_executor(mocks: SimpleNamespace) -> None:
    mocks.buscar_anamnese.return_value = _anamnese(executor_id=None)

    _criar(PACIENTE)

    assert mocks.inserir.await_args.kwargs["executor_id"] == PACIENTE_ID


def test_profissional_vinculado_cria_para_o_titular_da_anamnese(mocks: SimpleNamespace) -> None:
    _criar(PROFISSIONAL)

    kwargs = mocks.inserir.await_args.kwargs
    assert (kwargs["paciente_id"], kwargs["executor_id"]) == (PACIENTE_ID, PROFISSIONAL_ID)


def test_profissional_sem_vinculo_falha_antes_do_storage(mocks: SimpleNamespace) -> None:
    mocks.tem_vinculo.return_value = False

    with pytest.raises(diagnostico_service.AnamneseNaoEncontradaError):
        _criar(PROFISSIONAL)

    mocks.salvar.assert_not_awaited()
    mocks.inserir.assert_not_awaited()


def test_profissional_nao_reaproveita_autoavaliacao_do_paciente(mocks: SimpleNamespace) -> None:
    mocks.buscar_anamnese.return_value = _anamnese(executor_id=PACIENTE_ID)

    with pytest.raises(diagnostico_service.AnamneseNaoEncontradaError):
        _criar(PROFISSIONAL)

    mocks.salvar.assert_not_awaited()


def test_paciente_nao_envia_imagem_de_anamnese_feita_pelo_profissional(
    mocks: SimpleNamespace,
) -> None:
    with pytest.raises(diagnostico_service.AnamneseNaoEncontradaError):
        _criar(PACIENTE)

    mocks.salvar.assert_not_awaited()


def test_anamnese_de_outro_paciente_nao_e_aceita(mocks: SimpleNamespace) -> None:
    mocks.buscar_anamnese.return_value = _anamnese(
        paciente_id=OUTRO_PACIENTE_ID, executor_id=OUTRO_PACIENTE_ID
    )

    with pytest.raises(diagnostico_service.AnamneseNaoEncontradaError):
        _criar(PACIENTE)

    mocks.salvar.assert_not_awaited()


def test_retry_devolve_diagnostico_existente_sem_novo_upload(mocks: SimpleNamespace) -> None:
    existente = _diagnostico()
    mocks.buscar_por_anamnese.return_value = existente

    with pytest.raises(diagnostico_service.AnamneseJaUtilizadaError) as exc_info:
        _criar(PROFISSIONAL)

    assert exc_info.value.diagnostico is existente
    mocks.salvar.assert_not_awaited()


def test_envio_concorrente_remove_arquivo_e_retorna_conflito(mocks: SimpleNamespace) -> None:
    existente = _diagnostico()
    mocks.buscar_por_anamnese.side_effect = [None, existente]
    mocks.inserir.side_effect = IntegrityError("insert", {}, Exception("unique"))

    with pytest.raises(diagnostico_service.AnamneseJaUtilizadaError) as exc_info:
        _criar(PROFISSIONAL)

    assert exc_info.value.diagnostico is existente
    mocks.remover.assert_awaited_once_with(URL_IMAGEM)


def test_falha_apos_upload_remove_arquivo_orfao(mocks: SimpleNamespace) -> None:
    mocks.inserir.side_effect = OperationalError("insert", {}, Exception("caiu"))

    with pytest.raises(OperationalError):
        _criar(PROFISSIONAL)

    mocks.remover.assert_awaited_once_with(URL_IMAGEM)


# ---------------------------------------------------------------------------
# HTTP — sem banco
# ---------------------------------------------------------------------------


@pytest.fixture
def autenticado_como() -> Iterator:
    """Troca o usuário do token; devolve uma função `(id, role) -> None`."""

    def _definir(usuario_id: uuid.UUID, role: str) -> None:
        async def _usuario() -> SimpleNamespace:
            return SimpleNamespace(id=usuario_id, role=role)

        app.dependency_overrides[current_active_user] = _usuario

    yield _definir
    app.dependency_overrides.pop(current_active_user, None)


def _payload_anamnese() -> dict:
    return {
        "versao_questionario": "2026-08-v1",
        "respostas": [
            {"pergunta_id": "mau_halito_ao_acordar", "valor": True},
            {"pergunta_id": "frequencia_escovacao", "valor": "2x ao dia"},
            {"pergunta_id": "avaliacao_propria_halito", "valor": 3},
        ],
    }


def _enviar_diagnostico(anamnese_id: int = 128):
    return client.post(
        "/api/v1/diagnosticos",
        data={"anamnese_id": str(anamnese_id), "parametros_captura": "{}"},
        files={"imagem": ("foto.jpg", b"imagem", "image/jpeg")},
        headers=AUTH_HEADERS,
    )


@pytest.mark.parametrize("paciente_alvo", [OUTRO_PACIENTE_ID, PACIENTE_ID])
def test_http_paciente_nao_usa_rota_de_atendimento(autenticado_como, paciente_alvo) -> None:
    autenticado_como(PACIENTE_ID, "paciente")

    response = client.post(
        f"/api/v1/pacientes/{paciente_alvo}/anamneses",
        json=_payload_anamnese(),
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 403


def test_http_admin_nao_usa_rota_de_atendimento(autenticado_como) -> None:
    autenticado_como(uuid.uuid4(), "admin")

    response = client.post(
        f"/api/v1/pacientes/{PACIENTE_ID}/anamneses",
        json=_payload_anamnese(),
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 403


def test_http_profissional_sem_vinculo_recebe_404_na_anamnese(
    autenticado_como, mocks: SimpleNamespace
) -> None:
    autenticado_como(PROFISSIONAL_ID, "profissional")
    mocks.tem_vinculo.return_value = False

    response = client.post(
        f"/api/v1/pacientes/{PACIENTE_ID}/anamneses",
        json=_payload_anamnese(),
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 404
    mocks.buscar_usuario.assert_not_awaited()


def test_http_paciente_inativo_recebe_404_na_anamnese(
    autenticado_como, mocks: SimpleNamespace
) -> None:
    autenticado_como(PROFISSIONAL_ID, "profissional")
    mocks.buscar_usuario.return_value = SimpleNamespace(id=PACIENTE_ID, is_active=False)

    response = client.post(
        f"/api/v1/pacientes/{PACIENTE_ID}/anamneses",
        json=_payload_anamnese(),
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 404


def test_http_profissional_sem_vinculo_recebe_404_no_diagnostico(
    autenticado_como, mocks: SimpleNamespace
) -> None:
    autenticado_como(PROFISSIONAL_ID, "profissional")
    mocks.tem_vinculo.return_value = False

    response = _enviar_diagnostico()

    assert response.status_code == 404
    mocks.salvar.assert_not_awaited()


def test_http_admin_nao_envia_diagnostico(autenticado_como, mocks: SimpleNamespace) -> None:
    autenticado_como(uuid.uuid4(), "admin")

    response = _enviar_diagnostico()

    assert response.status_code == 403
    mocks.buscar_anamnese.assert_not_awaited()


def test_http_retry_retorna_409_com_diagnostico_existente(
    autenticado_como, mocks: SimpleNamespace
) -> None:
    autenticado_como(PROFISSIONAL_ID, "profissional")
    mocks.buscar_por_anamnese.return_value = _diagnostico()

    response = _enviar_diagnostico()

    assert response.status_code == 409
    assert response.json() == {
        "detail": "anamnese já vinculada a outro diagnóstico",
        "diagnostico_id": 4,
        "status": "processando",
    }
    mocks.salvar.assert_not_awaited()


def test_http_profissional_vinculado_recebe_202(autenticado_como, mocks: SimpleNamespace) -> None:
    autenticado_como(PROFISSIONAL_ID, "profissional")

    response = _enviar_diagnostico()

    assert response.status_code == 202
    assert response.json()["id"] == 4
    assert mocks.inserir.await_args.kwargs["paciente_id"] == PACIENTE_ID


def test_http_paciente_id_invalido_na_rota_retorna_422(autenticado_como) -> None:
    autenticado_como(PROFISSIONAL_ID, "profissional")

    response = client.post(
        "/api/v1/pacientes/abc/anamneses", json=_payload_anamnese(), headers=AUTH_HEADERS
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Integração — Postgres real
# ---------------------------------------------------------------------------


@dataclass
class Cenario:
    profissional_id: uuid.UUID
    paciente_id: uuid.UUID
    paciente_sem_vinculo_id: uuid.UUID


def _session_factory():
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _criar_cenario() -> Cenario:
    engine, factory = _session_factory()
    token = uuid.uuid4().hex[:12]
    cenario = Cenario(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    try:
        async with factory() as db:
            db.add_all(
                [
                    User(
                        id=cenario.profissional_id,
                        name="Profissional US-090",
                        email=f"prof.{token}@hality.local",
                        hashed_password="x",
                        role="profissional",
                    ),
                    User(
                        id=cenario.paciente_id,
                        name="Paciente vinculado US-090",
                        email=f"pac.{token}@hality.local",
                        hashed_password="x",
                        role="paciente",
                    ),
                    User(
                        id=cenario.paciente_sem_vinculo_id,
                        name="Paciente sem vinculo US-090",
                        email=f"pac.sem.{token}@hality.local",
                        hashed_password="x",
                        role="paciente",
                    ),
                ]
            )
            await db.flush()
            db.add(Profissional(usuario_id=cenario.profissional_id))
            await db.flush()
            db.add(
                PacienteProfissional(
                    paciente_id=cenario.paciente_id,
                    profissional_id=cenario.profissional_id,
                )
            )
            await db.commit()
        return cenario
    finally:
        await engine.dispose()


async def _remover_cenario(cenario: Cenario) -> None:
    # users -> cascata em profissionais, vínculos, anamneses, diagnósticos e imagens.
    engine, factory = _session_factory()
    try:
        async with factory() as db:
            await db.execute(
                delete(User).where(
                    User.id.in_(
                        [
                            cenario.paciente_id,
                            cenario.paciente_sem_vinculo_id,
                            cenario.profissional_id,
                        ]
                    )
                )
            )
            await db.commit()
    finally:
        await engine.dispose()


async def _consultar(consulta):
    engine, factory = _session_factory()
    try:
        async with factory() as db:
            return (await db.execute(consulta)).all()
    finally:
        await engine.dispose()


@pytest.fixture
def cenario(monkeypatch: pytest.MonkeyPatch, autenticado_como) -> Iterator[Cenario]:
    criado = asyncio.run(_criar_cenario())
    salvar = AsyncMock(return_value=URL_IMAGEM)
    monkeypatch.setattr(diagnostico_service.diagnostico_storage, "salvar", salvar)
    monkeypatch.setattr(diagnostico_service.diagnostico_storage, "remover", AsyncMock())
    # Fixa o catálogo estático (versão do payload) sem mexer em `questionarios`.
    monkeypatch.setattr(
        anamnese_service,
        "get_questionario_ativo",
        AsyncMock(return_value=anamnese_questionary._QUESTIONARIO_FALLBACK),
    )
    autenticado_como(criado.profissional_id, "profissional")
    try:
        yield criado
    finally:
        asyncio.run(_remover_cenario(criado))


def test_integracao_profissional_vinculado_registra_no_historico_do_paciente(
    cenario: Cenario,
) -> None:
    anamnese = client.post(
        f"/api/v1/pacientes/{cenario.paciente_id}/anamneses",
        json=_payload_anamnese(),
        headers=AUTH_HEADERS,
    )
    assert anamnese.status_code == 201
    assert anamnese.json()["paciente_id"] == str(cenario.paciente_id)
    anamnese_id = anamnese.json()["id"]

    primeiro = _enviar_diagnostico(anamnese_id)
    retry = _enviar_diagnostico(anamnese_id)

    assert primeiro.status_code == 202
    assert retry.status_code == 409
    assert retry.json()["diagnostico_id"] == primeiro.json()["id"]

    [(anamnese_paciente, anamnese_executor)] = asyncio.run(
        _consultar(
            select(Anamnese.paciente_id, Anamnese.executor_id).where(Anamnese.id == anamnese_id)
        )
    )
    [(diag_paciente, diag_executor)] = asyncio.run(
        _consultar(
            select(Diagnostico.paciente_id, Diagnostico.executor_id).where(
                Diagnostico.anamnese_id == anamnese_id
            )
        )
    )
    [(total_imagens,)] = asyncio.run(
        _consultar(
            select(func.count())
            .select_from(Imagem)
            .where(Imagem.diagnostico_id == primeiro.json()["id"])
        )
    )
    assert (anamnese_paciente, anamnese_executor) == (
        cenario.paciente_id,
        cenario.profissional_id,
    )
    assert (diag_paciente, diag_executor) == (cenario.paciente_id, cenario.profissional_id)
    assert total_imagens == 1

    detalhe = client.get(f"/api/v1/diagnosticos/{primeiro.json()['id']}", headers=AUTH_HEADERS)
    assert detalhe.status_code == 200


def test_integracao_paciente_sem_vinculo_nao_gera_registros(cenario: Cenario) -> None:
    response = client.post(
        f"/api/v1/pacientes/{cenario.paciente_sem_vinculo_id}/anamneses",
        json=_payload_anamnese(),
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 404
    [(total,)] = asyncio.run(
        _consultar(
            select(func.count())
            .select_from(Anamnese)
            .where(Anamnese.paciente_id == cenario.paciente_sem_vinculo_id)
        )
    )
    assert total == 0


def test_integracao_autoavaliacao_grava_paciente_como_executor(
    cenario: Cenario, autenticado_como
) -> None:
    autenticado_como(cenario.paciente_id, "paciente")

    response = client.post("/api/v1/anamneses", json=_payload_anamnese(), headers=AUTH_HEADERS)

    assert response.status_code == 201
    [(executor,)] = asyncio.run(
        _consultar(select(Anamnese.executor_id).where(Anamnese.id == response.json()["id"]))
    )
    assert executor == cenario.paciente_id
