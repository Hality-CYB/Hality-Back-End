import asyncio
import dataclasses
import hashlib
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
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.consentimentos import TERMOS, Finalidade
from app.core.erros_diagnostico import MENSAGENS, CodigoErroDiagnostico
from app.db import diagnostico_queries
from app.main import app
from app.models import (
    Anamnese,
    ClassificacaoDiagnostico,
    ConsentimentoEvento,
    Diagnostico,
    Imagem,
    User,
)
from app.services import diagnostico_mock, diagnostico_service, diagnostico_storage

client = TestClient(app)

AUTH_HEADERS = {"Authorization": "Bearer fake-token"}
PACIENTE_STUB_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_OUTRO_PACIENTE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
PACIENTE_STUB = SimpleNamespace(id=PACIENTE_STUB_ID, role="paciente")
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
        executor_id=paciente_id,
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
        origem_resultado=None,
        modelo_provider=None,
        modelo_versao=None,
        erro_codigo=None,
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
                    status = "processando"
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

    # `db` é um AsyncMock aqui: neutraliza a consulta de consentimento.
    monkeypatch.setattr(
        diagnostico_service.consentimento_service,
        "exigir_tratamento_vigente_se_decidido",
        AsyncMock(return_value=None),
    )

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

    inserir = AsyncMock(return_value=diagnostico)
    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "inserir",
        inserir,
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
            usuario=PACIENTE_STUB,
            anamnese_id=128,
            imagem=b"imagem",
            content_type="image/jpeg",
            parametros_captura={},
        )
    )

    assert resultado.id == 4
    assert resultado.status == "processando"
    assert resultado.anamnese_id == 128

    assert inserir.await_args.kwargs["arquivo"] == diagnostico_queries.ArquivoImagem(
        url_arquivo="/imagem.jpg",
        sha256=hashlib.sha256(b"imagem").hexdigest(),
        content_type="image/jpeg",
        tamanho_bytes=len(b"imagem"),
    )


def _criar_anamnese_do_paciente_stub() -> int:
    async def _criar() -> int:
        db, engine = await _abrir_sessao_teste()
        try:
            async with db:
                anamnese = Anamnese(
                    paciente_id=PACIENTE_STUB_ID,
                    id_versao_questionario=VERSAO_QUESTIONARIO_TESTE,
                    respostas=[],
                )
                db.add(anamnese)
                await db.commit()
                return anamnese.id
        finally:
            await engine.dispose()

    return asyncio.run(_criar())


def _registrar_decisao_de_tratamento(aceito: bool, versao: str = "v1") -> int:
    return _registrar_decisao(Finalidade.HEALTH_DATA, aceito, versao)


def _registrar_decisao(finalidade: Finalidade, aceito: bool, versao: str = "v1") -> int:
    async def _registrar() -> int:
        db, engine = await _abrir_sessao_teste()
        try:
            async with db:
                evento = ConsentimentoEvento(
                    titular_id=PACIENTE_STUB_ID,
                    finalidade=finalidade.value,
                    versao=versao,
                    aceito=aceito,
                    origem="perfil",
                    ator_id=PACIENTE_STUB_ID,
                    ator_papel="paciente",
                )
                db.add(evento)
                await db.commit()
                return evento.id
        finally:
            await engine.dispose()

    return asyncio.run(_registrar())


def _contar_diagnosticos_da_anamnese(anamnese_id: int) -> int:
    async def _contar() -> int:
        db, engine = await _abrir_sessao_teste()
        try:
            async with db:
                ids = await db.scalars(
                    select(Diagnostico.id).where(Diagnostico.anamnese_id == anamnese_id)
                )
                return len(list(ids))
        finally:
            await engine.dispose()

    return asyncio.run(_contar())


def _limpar_consentimento_e_anamnese(evento_ids: list[int], anamnese_id: int) -> None:
    async def _limpar() -> None:
        db, engine = await _abrir_sessao_teste()
        try:
            async with db:
                await db.execute(
                    delete(ConsentimentoEvento).where(ConsentimentoEvento.id.in_(evento_ids))
                )
                await db.execute(delete(Diagnostico).where(Diagnostico.anamnese_id == anamnese_id))
                await db.execute(delete(Anamnese).where(Anamnese.id == anamnese_id))
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(_limpar())


JPEG_MINIMO = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"0" * 64


def _enviar_diagnostico(anamnese_id: int):
    return client.post(
        "/api/v1/diagnosticos",
        headers=AUTH_HEADERS,
        data={"anamnese_id": str(anamnese_id), "parametros_captura": "{}"},
        files={"imagem": ("lingua.jpg", JPEG_MINIMO, "image/jpeg")},
    )


def test_criar_diagnostico_apos_revogar_tratamento_retorna_403() -> None:
    anamnese_id = _criar_anamnese_do_paciente_stub()
    evento_ids = [_registrar_decisao_de_tratamento(aceito=True)]
    try:
        evento_ids.append(_registrar_decisao_de_tratamento(aceito=False))

        resposta = _enviar_diagnostico(anamnese_id)

        assert resposta.status_code == 403
        assert "não vigente" in resposta.json()["detail"]
        assert _contar_diagnosticos_da_anamnese(anamnese_id) == 0
    finally:
        _limpar_consentimento_e_anamnese(evento_ids, anamnese_id)


def test_criar_diagnostico_com_aceite_de_versao_antiga_retorna_403(monkeypatch) -> None:
    anamnese_id = _criar_anamnese_do_paciente_stub()
    # Aceite dado na v1; o termo de tratamento passa a ser v2.
    evento_ids = [_registrar_decisao_de_tratamento(aceito=True, versao="v1")]
    termo_v2 = dataclasses.replace(TERMOS[Finalidade.HEALTH_DATA], versao="v2")
    monkeypatch.setitem(TERMOS, Finalidade.HEALTH_DATA, termo_v2)
    try:
        resposta = _enviar_diagnostico(anamnese_id)

        assert resposta.status_code == 403
        assert "não vigente" in resposta.json()["detail"]
        assert _contar_diagnosticos_da_anamnese(anamnese_id) == 0
    finally:
        _limpar_consentimento_e_anamnese(evento_ids, anamnese_id)


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
                usuario=PACIENTE_STUB,
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
                usuario=PACIENTE_STUB,
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


def test_listar_diagnosticos_processando_sem_resultado(
    diagnosticos_para_listagem: None,
) -> None:
    response = client.get(
        "/api/v1/diagnosticos",
        params={
            "status": "processando",
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
    assert item["status"] == "processando"
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


def test_listar_diagnosticos_prioriza_classificacao_da_revisao(monkeypatch) -> None:
    diagnostico = SimpleNamespace(
        id=42,
        data_diagnostico=datetime.now(UTC),
        status="concluido",
        classificacao_id=1,
        escala_saburra=2,
    )
    classificacao_automatica = SimpleNamespace(
        codigo="halito_normal",
        nome_exibicao="Hálito Normal",
        ordem=1,
    )
    classificacao_revisada = SimpleNamespace(
        codigo="halitose_intima",
        nome_exibicao="Halitose Íntima",
        ordem=3,
    )
    revisao = SimpleNamespace(classificacao=classificacao_revisada)

    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "listar_por_paciente",
        AsyncMock(
            return_value=SimpleNamespace(
                itens=[
                    SimpleNamespace(
                        diagnostico=diagnostico,
                        classificacao=classificacao_automatica,
                    )
                ],
                total=1,
            )
        ),
    )
    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "buscar_ultimas_revisoes",
        AsyncMock(return_value={42: revisao}),
    )

    resultado = asyncio.run(
        diagnostico_service.listar_diagnosticos(
            db=AsyncMock(),
            paciente_id=PACIENTE_STUB_ID,
        )
    )

    assert resultado.itens[0].classificacao.codigo == "halitose_intima"
    assert resultado.itens[0].classificacao.nome_exibicao == "Halitose Íntima"


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


@pytest.mark.asyncio
async def test_query_conteudos_diagnostico_filtra_destino_orientacoes():
    resultado = SimpleNamespace()
    resultado.scalars = lambda: SimpleNamespace(all=lambda: [])

    db = AsyncMock()
    db.execute.return_value = resultado

    assert await diagnostico_queries.listar_conteudos_por_classificacao(db, 3) == []

    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "ANY (conteudos.classificacao_ids)" in sql
    assert "ANY (conteudos.destinos)" in sql
    assert "conteudos.status" in sql
    assert "ORDER BY conteudos.ordem ASC, conteudos.id ASC" in sql


ERRO_INTERNO_TESTE = "stacktrace interno: conexão recusada pelo provider"
DATA_FUTURA = datetime(2099, 1, 1, tzinfo=UTC)


@dataclass
class DiagnosticoDeStatus:
    diagnostico_id: int
    anamnese_id: int
    classificacao_id: int
    classificacao_criada: bool


def _criar_diagnostico_com_status(status: str) -> DiagnosticoDeStatus:
    async def _criar() -> DiagnosticoDeStatus:
        db, engine = await _abrir_sessao_teste()
        try:
            async with db:
                classificacao = await db.scalar(
                    select(ClassificacaoDiagnostico).where(ClassificacaoDiagnostico.ordem == 1)
                )
                classificacao_criada = classificacao is None
                if classificacao is None:
                    classificacao = ClassificacaoDiagnostico(
                        codigo=f"{CLASSIFICACAO_TESTE_PREFIX}{uuid4().hex[:12]}",
                        nome_exibicao="Hálito Normal",
                        ordem=1,
                    )
                    db.add(classificacao)
                anamnese = Anamnese(
                    paciente_id=PACIENTE_STUB_ID,
                    id_versao_questionario=VERSAO_QUESTIONARIO_TESTE,
                    respostas=[],
                )
                db.add(anamnese)
                await db.flush()

                diagnostico = Diagnostico(
                    paciente_id=PACIENTE_STUB_ID,
                    anamnese_id=anamnese.id,
                    classificacao_id=classificacao.id,
                    escala_saburra=40,
                    confianca_ia=0.5,
                    status=status,
                    origem_resultado=None if status == "processando" else "mock",
                    erro_codigo="falha_processamento" if status == "falha" else None,
                    erro=ERRO_INTERNO_TESTE if status == "falha" else None,
                    data_diagnostico=DATA_FUTURA,
                )
                db.add(diagnostico)
                await db.commit()
                return DiagnosticoDeStatus(
                    diagnostico.id, anamnese.id, classificacao.id, classificacao_criada
                )
        finally:
            await engine.dispose()

    return asyncio.run(_criar())


def _remover_diagnostico_com_status(criado: DiagnosticoDeStatus) -> None:
    async def _remover() -> None:
        db, engine = await _abrir_sessao_teste()
        try:
            async with db:
                await db.execute(delete(Diagnostico).where(Diagnostico.id == criado.diagnostico_id))
                await db.execute(delete(Anamnese).where(Anamnese.id == criado.anamnese_id))
                if criado.classificacao_criada:
                    await db.execute(
                        delete(ClassificacaoDiagnostico).where(
                            ClassificacaoDiagnostico.id == criado.classificacao_id
                        )
                    )
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(_remover())


@pytest.fixture
def diagnostico_de_status(request: pytest.FixtureRequest) -> Iterator[DiagnosticoDeStatus]:
    criado = _criar_diagnostico_com_status(request.param)
    try:
        yield criado
    finally:
        _remover_diagnostico_com_status(criado)


@pytest.mark.parametrize("diagnostico_de_status", ["processando", "falha"], indirect=True)
def test_detalhe_sem_resultado_anula_saida_automatica(
    diagnostico_de_status: DiagnosticoDeStatus,
) -> None:
    resposta = client.get(
        f"/api/v1/diagnosticos/{diagnostico_de_status.diagnostico_id}", headers=AUTH_HEADERS
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["classificacao"] is None
    assert corpo["escala_saburra"] is None
    assert corpo["confianca_ia"] is None
    assert corpo["revisao"] is None
    assert corpo["conteudos"] == []


@pytest.mark.parametrize("diagnostico_de_status", ["falha"], indirect=True)
def test_detalhe_de_falha_expoe_somente_erro_publico(
    diagnostico_de_status: DiagnosticoDeStatus,
) -> None:
    resposta = client.get(
        f"/api/v1/diagnosticos/{diagnostico_de_status.diagnostico_id}", headers=AUTH_HEADERS
    )

    corpo = resposta.json()
    assert corpo["erro_codigo"] == "falha_processamento"
    assert corpo["erro"] == MENSAGENS[CodigoErroDiagnostico.FALHA_PROCESSAMENTO]
    assert ERRO_INTERNO_TESTE not in resposta.text


@pytest.mark.parametrize(
    "diagnostico_de_status", ["processando", "aguardando_revisao", "concluido"], indirect=True
)
def test_detalhe_fora_de_falha_nao_tem_erro(diagnostico_de_status: DiagnosticoDeStatus) -> None:
    corpo = client.get(
        f"/api/v1/diagnosticos/{diagnostico_de_status.diagnostico_id}", headers=AUTH_HEADERS
    ).json()

    assert corpo["erro"] is None
    assert corpo["erro_codigo"] is None


@pytest.mark.parametrize(
    "diagnostico_de_status", ["aguardando_revisao", "concluido"], indirect=True
)
def test_detalhe_com_resultado_expoe_saida_sem_origem(
    diagnostico_de_status: DiagnosticoDeStatus,
) -> None:
    corpo = client.get(
        f"/api/v1/diagnosticos/{diagnostico_de_status.diagnostico_id}", headers=AUTH_HEADERS
    ).json()

    assert corpo["classificacao"]["id"] == diagnostico_de_status.classificacao_id
    assert corpo["escala_saburra"] == 40
    assert corpo["confianca_ia"] == pytest.approx(0.5)
    assert "origem" not in corpo


def test_mock_sem_classificacao_configurada_falha_com_codigo_publico(monkeypatch) -> None:
    diagnostico = _diagnostico()
    diagnostico.data_diagnostico = datetime.now(UTC) - timedelta(minutes=1)
    monkeypatch.setattr(
        diagnostico_queries, "buscar_classificacao_por_ordem", AsyncMock(return_value=None)
    )

    asyncio.run(diagnostico_mock.processar_se_necessario(AsyncMock(), diagnostico))

    assert diagnostico.status == "falha"
    assert diagnostico.erro_codigo == "classificacao_nao_configurada"
    assert diagnostico.origem_resultado == "mock"
    assert diagnostico.modelo_provider is None
    assert diagnostico.modelo_versao is None
    assert diagnostico.classificacao_id is None
    assert diagnostico.erro


def test_falha_ao_gravar_diagnostico_remove_original_do_storage(monkeypatch) -> None:
    monkeypatch.setattr(
        diagnostico_service.consentimento_service,
        "exigir_tratamento_vigente_se_decidido",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        diagnostico_service.anamnese_queries, "buscar_por_id", AsyncMock(return_value=_anamnese())
    )
    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "buscar_por_anamnese",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        diagnostico_service.diagnostico_queries,
        "inserir",
        AsyncMock(side_effect=RuntimeError("banco indisponível")),
    )
    monkeypatch.setattr(
        diagnostico_service.diagnostico_storage, "salvar", AsyncMock(return_value="/x/a.jpg")
    )
    remover = AsyncMock()
    monkeypatch.setattr(diagnostico_service.diagnostico_storage, "remover", remover)
    db = AsyncMock()

    with pytest.raises(RuntimeError):
        asyncio.run(
            diagnostico_service.criar_diagnostico(
                db=db,
                usuario=PACIENTE_STUB,
                anamnese_id=128,
                imagem=b"imagem",
                content_type="image/jpeg",
                parametros_captura={},
            )
        )

    remover.assert_awaited_once_with("/x/a.jpg")
    db.rollback.assert_awaited_once()


def test_storage_nao_sobrescreve_original(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(diagnostico_storage, "_STORAGE_DIR", tmp_path)
    nome_fixo = SimpleNamespace(hex="mesmo-nome")
    monkeypatch.setattr(diagnostico_storage, "uuid4", lambda: nome_fixo)

    asyncio.run(diagnostico_storage.salvar(b"original", "image/jpeg", "/api/v1"))

    with pytest.raises(FileExistsError):
        asyncio.run(diagnostico_storage.salvar(b"outra", "image/jpeg", "/api/v1"))

    assert (tmp_path / "mesmo-nome.jpg").read_bytes() == b"original"


def _imagens_da_anamnese(anamnese_id: int) -> list[Imagem]:
    async def _listar() -> list[Imagem]:
        db, engine = await _abrir_sessao_teste()
        try:
            async with db:
                return list(
                    await db.scalars(
                        select(Imagem)
                        .join(Diagnostico, Diagnostico.id == Imagem.diagnostico_id)
                        .where(Diagnostico.anamnese_id == anamnese_id)
                    )
                )
        finally:
            await engine.dispose()

    return asyncio.run(_listar())


def _remover_arquivos(imagens: list[Imagem]) -> None:
    for imagem in imagens:
        asyncio.run(diagnostico_storage.remover(imagem.url_arquivo))


def test_reenvio_da_mesma_anamnese_e_idempotente() -> None:
    anamnese_id = _criar_anamnese_do_paciente_stub()
    imagens: list[Imagem] = []
    try:
        primeira = _enviar_diagnostico(anamnese_id)
        assert primeira.status_code == 202
        imagens = _imagens_da_anamnese(anamnese_id)

        segunda = _enviar_diagnostico(anamnese_id)

        assert segunda.status_code == 409
        assert segunda.json()["diagnostico_id"] == primeira.json()["id"]
        assert segunda.json()["status"] == "processando"
        assert _contar_diagnosticos_da_anamnese(anamnese_id) == 1
        assert len(_imagens_da_anamnese(anamnese_id)) == 1
        imagem = imagens[0]
        assert imagem.sha256 == hashlib.sha256(JPEG_MINIMO).hexdigest()
        assert imagem.tamanho_bytes == len(JPEG_MINIMO)
        assert imagem.content_type == "image/jpeg"
        caminho = diagnostico_storage.resolver_caminho(imagem.url_arquivo.rsplit("/", 1)[-1])
        assert caminho is not None
        assert caminho.read_bytes() == JPEG_MINIMO
    finally:
        _remover_arquivos(imagens)
        _limpar_consentimento_e_anamnese([], anamnese_id)


def test_recusa_de_treino_nao_bloqueia_diagnostico() -> None:
    anamnese_id = _criar_anamnese_do_paciente_stub()
    evento_ids = [
        _registrar_decisao(Finalidade.HEALTH_DATA, aceito=True),
        _registrar_decisao(Finalidade.IMAGE_TRAINING, aceito=True),
    ]
    try:
        evento_ids.append(_registrar_decisao(Finalidade.IMAGE_TRAINING, aceito=False))

        resposta = _enviar_diagnostico(anamnese_id)

        assert resposta.status_code == 202
    finally:
        _remover_arquivos(_imagens_da_anamnese(anamnese_id))
        _limpar_consentimento_e_anamnese(evento_ids, anamnese_id)
