import asyncio
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.main import app
from app.models import Anamnese, ClassificacaoDiagnostico, Diagnostico, User
from app.services import diagnostico_mock, diagnostico_service

client = TestClient(app)

AUTH_HEADERS = {"Authorization": "Bearer fake-token"}
PACIENTE_STUB_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_OUTRO_PACIENTE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
PACIENTE_ID_QUERY_IGNORADO = 998
CLASSIFICACAO_TESTE_PREFIX = "TESTE_LISTAGEM_"
VERSAO_QUESTIONARIO_TESTE = "2026-08-v1"
DATA_BASE_LISTAGEM = datetime(2099, 8, 1, 9, 14, tzinfo=UTC)
DATA_INICIO_LISTAGEM = DATA_BASE_LISTAGEM.date().isoformat()
DATA_FIM_LISTAGEM = (DATA_BASE_LISTAGEM + timedelta(days=11)).date().isoformat()


def _anamnese(paciente_id=PACIENTE_STUB_ID):
    return SimpleNamespace(
        id=128,
        paciente_id=paciente_id,
        data_preenchimento=datetime.now(UTC),
        respostas=[],
    )


def _diagnostico(
    paciente_id=PACIENTE_STUB_ID,
    status="processando",
):
    return SimpleNamespace(
        id=4,
        paciente_id=paciente_id,
        anamnese_id=128,
        status=status,
        data_diagnostico=datetime.now(UTC),
        classificacao_id=None,
        escala_saburra=None,
        confianca_ia=None,
        profissional_revisor_id=None,
        data_revisao=None,
        observacoes_revisao=None,
        nivel_corrigido=False,
        erro=None,
    )


@dataclass
class DiagnosticosListagemCriados:
    anamnese_ids: list[int] = field(default_factory=list)
    diagnostico_ids: list[int] = field(default_factory=list)
    classificacao_id: int | None = None
    outro_paciente_id: uuid.UUID | None = None


@pytest.fixture
def diagnosticos_para_listagem() -> Iterator[None]:
    criados = asyncio.run(_preparar_diagnosticos_para_listagem())
    try:
        yield
    finally:
        asyncio.run(_limpar_diagnosticos_para_listagem(criados))


async def _abrir_sessao_teste() -> tuple[AsyncSession, object]:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return session_factory(), engine


async def _gerar_outro_paciente_id(db: AsyncSession) -> uuid.UUID:
    for _ in range(10):
        candidato = uuid4()

        if await db.get(User, candidato) is None:
            return candidato

    raise RuntimeError("nao foi possivel gerar id unico para paciente auxiliar")


async def _preparar_diagnosticos_para_listagem() -> DiagnosticosListagemCriados:
    db, engine = await _abrir_sessao_teste()
    criados = DiagnosticosListagemCriados()

    try:
        async with db:
            token = uuid4().hex
            outro_paciente_id = await _gerar_outro_paciente_id(db)
            outro_paciente = User(
                id=outro_paciente_id,
                name="Paciente Fora da Listagem",
                email=f"paciente.fora.listagem.{token}@hality.local",
                hashed_password="x",
                role="paciente",
            )
            db.add(outro_paciente)
            await db.flush()
            criados.outro_paciente_id = outro_paciente.id

            classificacao = await db.scalar(
                select(ClassificacaoDiagnostico).where(ClassificacaoDiagnostico.ordem == 3)
            )
            if classificacao is None:
                classificacao = ClassificacaoDiagnostico(
                    codigo=f"{CLASSIFICACAO_TESTE_PREFIX}{token[:12]}",
                    nome_exibicao="Mau Hálito Social",
                    ordem=3,
                )
                db.add(classificacao)
                await db.flush()
                criados.classificacao_id = classificacao.id

            for indice in range(12):
                anamnese = Anamnese(
                    paciente_id=PACIENTE_STUB_ID,
                    id_versao_questionario=VERSAO_QUESTIONARIO_TESTE,
                    respostas=[
                        {
                            "pergunta_id": "teste_listagem",
                            "enunciado": "Teste listagem",
                            "tipo": "text",
                            "valor": str(indice),
                        }
                    ],
                )
                db.add(anamnese)
                await db.flush()
                criados.anamnese_ids.append(anamnese.id)

                status = "concluido"
                classificacao_id = classificacao.id
                escala_saburra = 60 + indice

                if indice == 3:
                    status = "aguardando_analise"
                    classificacao_id = None
                    escala_saburra = None
                elif indice == 5:
                    status = "falha"
                    classificacao_id = None
                    escala_saburra = None

                diagnostico = Diagnostico(
                    paciente_id=PACIENTE_STUB_ID,
                    anamnese_id=anamnese.id,
                    classificacao_id=classificacao_id,
                    escala_saburra=escala_saburra,
                    confianca_ia=0.91 if classificacao_id is not None else None,
                    status=status,
                    data_diagnostico=DATA_BASE_LISTAGEM + timedelta(days=indice),
                )
                db.add(diagnostico)
                await db.flush()
                criados.diagnostico_ids.append(diagnostico.id)

            anamnese_outro_paciente = Anamnese(
                paciente_id=outro_paciente.id,
                id_versao_questionario=VERSAO_QUESTIONARIO_TESTE,
                respostas=[
                    {
                        "pergunta_id": "teste_listagem",
                        "enunciado": "Teste listagem",
                        "tipo": "text",
                        "valor": "outro",
                    }
                ],
            )
            db.add(anamnese_outro_paciente)
            await db.flush()
            criados.anamnese_ids.append(anamnese_outro_paciente.id)

            diagnostico_outro_paciente = Diagnostico(
                paciente_id=outro_paciente.id,
                anamnese_id=anamnese_outro_paciente.id,
                classificacao_id=classificacao.id,
                escala_saburra=99,
                confianca_ia=0.99,
                status="concluido",
                data_diagnostico=DATA_BASE_LISTAGEM + timedelta(days=30),
            )
            db.add(diagnostico_outro_paciente)
            await db.flush()
            criados.diagnostico_ids.append(diagnostico_outro_paciente.id)

            await db.commit()
            return criados
    except Exception:
        await db.rollback()
        raise
    finally:
        await engine.dispose()


async def _limpar_diagnosticos_para_listagem(criados: DiagnosticosListagemCriados) -> None:
    db, engine = await _abrir_sessao_teste()

    try:
        async with db:
            if criados.diagnostico_ids:
                await db.execute(
                    delete(Diagnostico).where(Diagnostico.id.in_(criados.diagnostico_ids))
                )

            if criados.anamnese_ids:
                await db.execute(delete(Anamnese).where(Anamnese.id.in_(criados.anamnese_ids)))

            if criados.classificacao_id is not None:
                await db.execute(
                    delete(ClassificacaoDiagnostico).where(
                        ClassificacaoDiagnostico.id == criados.classificacao_id
                    )
                )

            if criados.outro_paciente_id is not None:
                await db.execute(delete(User).where(User.id == criados.outro_paciente_id))

            await db.commit()
    finally:
        await engine.dispose()


def test_criar_diagnostico(monkeypatch):
    diagnostico = _diagnostico()

    monkeypatch.setattr(
        diagnostico_service.anamnese_queries,
        "buscar_por_id",
        AsyncMock(return_value=_anamnese()),
    )

    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "buscar_por_anamnese",
        AsyncMock(return_value=None),
    )

    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "inserir",
        AsyncMock(return_value=diagnostico),
    )

    monkeypatch.setattr(
        diagnostico_service.diagnostico_storage,
        "salvar",
        AsyncMock(return_value="/imagem.jpg"),
    )

    monkeypatch.setattr(
        diagnostico_service,
        "get_settings",
        lambda: SimpleNamespace(api_v1_prefix="/api/v1"),
    )

    resultado = asyncio.run(
        diagnostico_service.criar_diagnostico(
            db=AsyncMock(),
            paciente_id=PACIENTE_STUB_ID,
            anamnese_id=128,
            imagem=b"imagem",
            content_type="image/jpeg",
            parametros_captura={},
        )
    )

    assert resultado["id"] == 4
    assert resultado["status"] == "processando"
    assert resultado["anamnese_id"] == 128


def test_anamnese_de_outro_paciente(
    monkeypatch,
):
    monkeypatch.setattr(
        diagnostico_service.anamnese_queries,
        "buscar_por_id",
        AsyncMock(return_value=_anamnese(paciente_id=_OUTRO_PACIENTE_ID)),
    )

    with pytest.raises(diagnostico_service.AnamneseNaoEncontradaError):
        asyncio.run(
            diagnostico_service.criar_diagnostico(
                db=AsyncMock(),
                paciente_id=PACIENTE_STUB_ID,
                anamnese_id=128,
                imagem=b"imagem",
                content_type="image/jpeg",
                parametros_captura={},
            )
        )


def test_anamnese_ja_utilizada(
    monkeypatch,
):
    monkeypatch.setattr(
        diagnostico_service.anamnese_queries,
        "buscar_por_id",
        AsyncMock(return_value=_anamnese()),
    )

    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "buscar_por_anamnese",
        AsyncMock(return_value=_diagnostico()),
    )

    with pytest.raises(diagnostico_service.AnamneseJaUtilizadaError):
        asyncio.run(
            diagnostico_service.criar_diagnostico(
                db=AsyncMock(),
                paciente_id=PACIENTE_STUB_ID,
                anamnese_id=128,
                imagem=b"imagem",
                content_type="image/jpeg",
                parametros_captura={},
            )
        )


def test_mock_cobre_os_tres_niveis():
    assert diagnostico_mock.resultado_para(1).ordem_classificacao == 1

    assert diagnostico_mock.resultado_para(2).ordem_classificacao == 2

    assert diagnostico_mock.resultado_para(3).ordem_classificacao == 3


def test_listar_diagnosticos_sem_token_retorna_401() -> None:
    response = client.get("/api/v1/diagnosticos")

    assert response.status_code == 401


def test_listar_diagnosticos_resposta_vazia() -> None:
    response = client.get(
        "/api/v1/diagnosticos",
        params={"status": f"vazio_{uuid4().hex[:10]}"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {
        "itens": [],
        "pagina": 1,
        "limite": 20,
        "total": 0,
        "total_paginas": 0,
    }


def test_listar_diagnosticos_defaults_e_paciente_autenticado(
    diagnosticos_para_listagem: None,
) -> None:
    response = client.get(
        "/api/v1/diagnosticos",
        params={
            "paciente_id": PACIENTE_ID_QUERY_IGNORADO,
            "data_inicio": DATA_INICIO_LISTAGEM,
            "data_fim": DATA_FIM_LISTAGEM,
        },
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    corpo = response.json()
    datas = [item["data_diagnostico"] for item in corpo["itens"]]

    assert corpo["pagina"] == 1
    assert corpo["limite"] == 20
    assert corpo["total"] == 12
    assert corpo["total_paginas"] == 1
    assert len(corpo["itens"]) == 12
    assert datas == sorted(datas, reverse=True)


def test_listar_diagnosticos_paginacao(
    diagnosticos_para_listagem: None,
) -> None:
    response = client.get(
        "/api/v1/diagnosticos",
        params={
            "pagina": 2,
            "limite": 5,
            "data_inicio": DATA_INICIO_LISTAGEM,
            "data_fim": DATA_FIM_LISTAGEM,
        },
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    corpo = response.json()

    assert corpo["pagina"] == 2
    assert corpo["limite"] == 5
    assert corpo["total"] == 12
    assert corpo["total_paginas"] == 3
    assert len(corpo["itens"]) == 5


def test_listar_diagnosticos_filtra_datas_inclusivas(
    diagnosticos_para_listagem: None,
) -> None:
    data_inicio = (DATA_BASE_LISTAGEM + timedelta(days=2)).date().isoformat()
    data_fim = (DATA_BASE_LISTAGEM + timedelta(days=4)).date().isoformat()

    response = client.get(
        "/api/v1/diagnosticos",
        params={
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "ordem": "data_asc",
            "limite": 50,
        },
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    corpo = response.json()
    datas = [item["data_diagnostico"] for item in corpo["itens"]]

    assert corpo["total"] == 3
    assert datas[0].startswith(data_inicio)
    assert datas[-1].startswith(data_fim)
    assert datas == sorted(datas)


def test_listar_diagnosticos_aguardando_analise_sem_resultado(
    diagnosticos_para_listagem: None,
) -> None:
    response = client.get(
        "/api/v1/diagnosticos",
        params={
            "status": "aguardando_analise",
            "limite": 50,
            "data_inicio": DATA_INICIO_LISTAGEM,
            "data_fim": DATA_FIM_LISTAGEM,
        },
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    corpo = response.json()
    item = corpo["itens"][0]

    assert corpo["total"] == 1
    assert item["status"] == "aguardando_analise"
    assert item["classificacao"] is None
    assert item["escala_saburra"] is None


def test_listar_diagnosticos_filtra_status(
    diagnosticos_para_listagem: None,
) -> None:
    response = client.get(
        "/api/v1/diagnosticos",
        params={
            "status": "falha",
            "limite": 50,
            "data_inicio": DATA_INICIO_LISTAGEM,
            "data_fim": DATA_FIM_LISTAGEM,
        },
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    corpo = response.json()

    assert corpo["total"] == 1
    assert corpo["itens"][0]["status"] == "falha"


def test_listar_diagnosticos_concluido_traz_ordem_da_classificacao(
    diagnosticos_para_listagem: None,
) -> None:
    response = client.get(
        "/api/v1/diagnosticos",
        params={
            "status": "concluido",
            "limite": 50,
            "data_inicio": DATA_INICIO_LISTAGEM,
            "data_fim": DATA_FIM_LISTAGEM,
        },
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    corpo = response.json()

    assert corpo["total"] == 10
    assert all(item["classificacao"]["ordem"] == 3 for item in corpo["itens"])


def test_listar_diagnosticos_data_inicio_maior_que_fim_retorna_400() -> None:
    response = client.get(
        "/api/v1/diagnosticos",
        params={"data_inicio": "2026-08-10", "data_fim": "2026-08-01"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400


def test_listar_diagnosticos_limite_maior_que_50_retorna_400() -> None:
    response = client.get(
        "/api/v1/diagnosticos",
        params={"limite": 51},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400
