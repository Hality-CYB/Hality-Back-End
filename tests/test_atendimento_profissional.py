"""US-090 — profissional registrando anamnese/diagnóstico para paciente vinculado.

Três blocos:

* **Service (sem banco)** — `criar_diagnostico` com queries/storage mockados:
  titularidade, vínculo negado antes do storage, retry idempotente e limpeza
  de arquivo órfão.
* **HTTP (sem banco)** — erros que precisam acontecer antes de qualquer
  leitura/escrita (403 de papel/vínculo) e o contrato do 409.
* **Integração (Postgres real do `.env`)** — fluxo ponta a ponta do
  profissional, conferindo `paciente_id`/`executor_id` gravados.
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
from app.services import (
    anamnese_questionary,
    anamnese_service,
    atendimento_service,
    diagnostico_service,
)
from app.services.atendimento_service import AtorAutenticado

AUTH_HEADERS = {"Authorization": "Bearer fake-token"}
PROFISSIONAL_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
PACIENTE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
OUTRO_PACIENTE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b2")

ATOR_PROFISSIONAL = AtorAutenticado(id=PROFISSIONAL_ID, role="profissional")
ATOR_PACIENTE = AtorAutenticado(id=PACIENTE_ID, role="paciente")

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
    """Queries e storage do fluxo de criação, todos mockados."""
    m = SimpleNamespace(
        buscar_anamnese=AsyncMock(return_value=_anamnese()),
        buscar_por_anamnese=AsyncMock(return_value=None),
        inserir=AsyncMock(return_value=_diagnostico()),
        salvar=AsyncMock(return_value=URL_IMAGEM),
        remover=AsyncMock(),
        existe_vinculo=AsyncMock(return_value=True),
        usuario_ativo=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(diagnostico_service.anamnese_queries, "buscar_por_id", m.buscar_anamnese)
    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries, "buscar_por_anamnese", m.buscar_por_anamnese
    )
    monkeypatch.setattr(diagnostico_service.diagnostico_queries, "inserir", m.inserir)
    monkeypatch.setattr(diagnostico_service.diagnostico_storage, "salvar", m.salvar)
    monkeypatch.setattr(diagnostico_service.diagnostico_storage, "remover", m.remover)
    monkeypatch.setattr(atendimento_service.vinculo_queries, "existe_vinculo", m.existe_vinculo)
    monkeypatch.setattr(atendimento_service.vinculo_queries, "usuario_ativo", m.usuario_ativo)
    monkeypatch.setattr(
        diagnostico_service,
        "get_settings",
        lambda: SimpleNamespace(api_v1_prefix="/api/v1"),
    )
    return m


def _criar(ator: AtorAutenticado, paciente_id: uuid.UUID | None = None, db=None):
    return asyncio.run(
        diagnostico_service.criar_diagnostico(
            db=db or AsyncMock(),
            ator=ator,
            anamnese_id=128,
            imagem=b"imagem",
            content_type="image/jpeg",
            parametros_captura={"flash": True},
            paciente_id=paciente_id,
        )
    )


# ---------------------------------------------------------------------------
# Service — sem banco
# ---------------------------------------------------------------------------


def test_paciente_continua_criando_para_si(mocks: SimpleNamespace) -> None:
    mocks.buscar_anamnese.return_value = _anamnese(PACIENTE_ID, executor_id=PACIENTE_ID)

    _criar(ATOR_PACIENTE)

    kwargs = mocks.inserir.await_args.kwargs
    assert kwargs["paciente_id"] == PACIENTE_ID
    assert kwargs["executor_id"] == PACIENTE_ID
    mocks.existe_vinculo.assert_not_awaited()


def test_paciente_usa_anamnese_legada_sem_executor(mocks: SimpleNamespace) -> None:
    mocks.buscar_anamnese.return_value = _anamnese(PACIENTE_ID, executor_id=None)

    _criar(ATOR_PACIENTE)

    assert mocks.inserir.await_args.kwargs["executor_id"] == PACIENTE_ID


def test_profissional_vinculado_cria_para_paciente_correto(mocks: SimpleNamespace) -> None:
    resultado = _criar(ATOR_PROFISSIONAL, paciente_id=PACIENTE_ID)

    kwargs = mocks.inserir.await_args.kwargs
    assert kwargs["paciente_id"] == PACIENTE_ID
    assert kwargs["executor_id"] == PROFISSIONAL_ID
    assert kwargs["url_arquivo"] == URL_IMAGEM
    assert kwargs["parametros_captura"] == {"flash": True}
    assert resultado["status"] == "processando"
    mocks.existe_vinculo.assert_awaited_once()


def test_profissional_nao_vinculado_falha_antes_do_storage(mocks: SimpleNamespace) -> None:
    mocks.existe_vinculo.return_value = False

    with pytest.raises(atendimento_service.VinculoInexistenteError):
        _criar(ATOR_PROFISSIONAL, paciente_id=PACIENTE_ID)

    mocks.buscar_anamnese.assert_not_awaited()
    mocks.salvar.assert_not_awaited()
    mocks.inserir.assert_not_awaited()


def test_paciente_nao_pode_informar_outro_titular(mocks: SimpleNamespace) -> None:
    with pytest.raises(atendimento_service.AtorNaoProfissionalError):
        _criar(ATOR_PACIENTE, paciente_id=OUTRO_PACIENTE_ID)

    mocks.buscar_anamnese.assert_not_awaited()
    mocks.salvar.assert_not_awaited()


def test_titular_inativo_retorna_indisponivel(mocks: SimpleNamespace) -> None:
    mocks.usuario_ativo.return_value = False

    with pytest.raises(atendimento_service.TitularIndisponivelError):
        _criar(ATOR_PROFISSIONAL, paciente_id=PACIENTE_ID)

    mocks.salvar.assert_not_awaited()


def test_profissional_nao_reaproveita_autoavaliacao_do_paciente(mocks: SimpleNamespace) -> None:
    mocks.buscar_anamnese.return_value = _anamnese(PACIENTE_ID, executor_id=PACIENTE_ID)

    with pytest.raises(diagnostico_service.AnamneseNaoEncontradaError):
        _criar(ATOR_PROFISSIONAL, paciente_id=PACIENTE_ID)

    mocks.salvar.assert_not_awaited()


def test_anamnese_de_outro_titular_nao_e_aceita(mocks: SimpleNamespace) -> None:
    mocks.buscar_anamnese.return_value = _anamnese(OUTRO_PACIENTE_ID)

    with pytest.raises(diagnostico_service.AnamneseNaoEncontradaError):
        _criar(ATOR_PROFISSIONAL, paciente_id=PACIENTE_ID)

    mocks.salvar.assert_not_awaited()


def test_retry_devolve_diagnostico_existente_sem_novo_upload(mocks: SimpleNamespace) -> None:
    existente = _diagnostico()
    mocks.buscar_por_anamnese.return_value = existente

    with pytest.raises(diagnostico_service.AnamneseJaUtilizadaError) as exc_info:
        _criar(ATOR_PROFISSIONAL, paciente_id=PACIENTE_ID)

    assert exc_info.value.diagnostico is existente
    mocks.salvar.assert_not_awaited()
    mocks.inserir.assert_not_awaited()


def test_envio_concorrente_remove_arquivo_e_retorna_conflito(mocks: SimpleNamespace) -> None:
    # Os dois envios passam pela checagem; o segundo bate na unique de anamnese_id.
    existente = _diagnostico()
    mocks.buscar_por_anamnese.side_effect = [None, existente]
    mocks.inserir.side_effect = IntegrityError("insert", {}, Exception("unique"))

    with pytest.raises(diagnostico_service.AnamneseJaUtilizadaError) as exc_info:
        _criar(ATOR_PROFISSIONAL, paciente_id=PACIENTE_ID)

    assert exc_info.value.diagnostico is existente
    mocks.remover.assert_awaited_once_with(URL_IMAGEM)


def test_falha_apos_upload_remove_arquivo_orfao(mocks: SimpleNamespace) -> None:
    mocks.inserir.side_effect = OperationalError("commit", {}, Exception("conexão caiu"))
    db = AsyncMock()

    with pytest.raises(OperationalError):
        _criar(ATOR_PROFISSIONAL, paciente_id=PACIENTE_ID, db=db)

    db.rollback.assert_awaited_once()
    mocks.remover.assert_awaited_once_with(URL_IMAGEM)


def test_pode_acessar_titular(mocks: SimpleNamespace) -> None:
    db = AsyncMock()

    assert asyncio.run(atendimento_service.pode_acessar_titular(db, ATOR_PACIENTE, PACIENTE_ID))
    assert asyncio.run(atendimento_service.pode_acessar_titular(db, ATOR_PROFISSIONAL, PACIENTE_ID))
    assert not asyncio.run(
        atendimento_service.pode_acessar_titular(db, ATOR_PACIENTE, OUTRO_PACIENTE_ID)
    )

    mocks.existe_vinculo.return_value = False
    assert not asyncio.run(
        atendimento_service.pode_acessar_titular(db, ATOR_PROFISSIONAL, PACIENTE_ID)
    )


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


def _enviar_diagnostico(paciente_id: uuid.UUID | None = None, anamnese_id: int = 128):
    dados = {"anamnese_id": str(anamnese_id), "parametros_captura": "{}"}
    if paciente_id is not None:
        dados["paciente_id"] = str(paciente_id)
    return client.post(
        "/api/v1/diagnosticos",
        data=dados,
        files={"imagem": ("foto.jpg", b"imagem", "image/jpeg")},
        headers=AUTH_HEADERS,
    )


def test_http_paciente_nao_usa_rota_de_atendimento(autenticado_como) -> None:
    autenticado_como(PACIENTE_ID, "paciente")

    response = client.post(
        f"/api/v1/pacientes/{OUTRO_PACIENTE_ID}/anamneses",
        json=_payload_anamnese(),
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 403


def test_http_paciente_nao_usa_rota_de_atendimento_nem_para_si(autenticado_como) -> None:
    autenticado_como(PACIENTE_ID, "paciente")

    response = client.post(
        f"/api/v1/pacientes/{PACIENTE_ID}/anamneses",
        json=_payload_anamnese(),
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 403


def test_http_profissional_sem_vinculo_recebe_403_na_anamnese(
    autenticado_como, mocks: SimpleNamespace
) -> None:
    autenticado_como(PROFISSIONAL_ID, "profissional")
    mocks.existe_vinculo.return_value = False

    response = client.post(
        f"/api/v1/pacientes/{PACIENTE_ID}/anamneses",
        json=_payload_anamnese(),
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "profissional sem vínculo com o paciente"


def test_http_profissional_sem_vinculo_recebe_403_no_diagnostico(
    autenticado_como, mocks: SimpleNamespace
) -> None:
    autenticado_como(PROFISSIONAL_ID, "profissional")
    mocks.existe_vinculo.return_value = False

    response = _enviar_diagnostico(paciente_id=PACIENTE_ID)

    assert response.status_code == 403
    mocks.buscar_anamnese.assert_not_awaited()
    mocks.salvar.assert_not_awaited()


def test_http_paciente_informando_outro_titular_recebe_403(
    autenticado_como, mocks: SimpleNamespace
) -> None:
    autenticado_como(PACIENTE_ID, "paciente")

    response = _enviar_diagnostico(paciente_id=OUTRO_PACIENTE_ID)

    assert response.status_code == 403
    mocks.salvar.assert_not_awaited()


def test_http_retry_retorna_409_com_diagnostico_existente(
    autenticado_como, mocks: SimpleNamespace
) -> None:
    autenticado_como(PROFISSIONAL_ID, "profissional")
    mocks.buscar_por_anamnese.return_value = _diagnostico()

    response = _enviar_diagnostico(paciente_id=PACIENTE_ID)

    assert response.status_code == 409
    assert response.json() == {
        "detail": "anamnese já vinculada a outro diagnóstico",
        "diagnostico_id": 4,
        "status": "processando",
    }
    mocks.salvar.assert_not_awaited()


def test_http_profissional_vinculado_recebe_202(autenticado_como, mocks: SimpleNamespace) -> None:
    autenticado_como(PROFISSIONAL_ID, "profissional")

    response = _enviar_diagnostico(paciente_id=PACIENTE_ID)

    assert response.status_code == 202
    assert response.json()["id"] == 4
    assert mocks.inserir.await_args.kwargs["paciente_id"] == PACIENTE_ID


def test_http_paciente_id_invalido_retorna_422(autenticado_como, mocks: SimpleNamespace) -> None:
    autenticado_como(PROFISSIONAL_ID, "profissional")

    response = client.post(
        "/api/v1/diagnosticos",
        data={"anamnese_id": "128", "parametros_captura": "{}", "paciente_id": "abc"},
        files={"imagem": ("foto.jpg", b"imagem", "image/jpeg")},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 422
    mocks.salvar.assert_not_awaited()


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

    primeiro = _enviar_diagnostico(cenario.paciente_id, anamnese_id)
    retry = _enviar_diagnostico(cenario.paciente_id, anamnese_id)

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

    assert response.status_code == 403
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
