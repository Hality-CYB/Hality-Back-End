"""Upload e leitura das imagens e vídeos dos conteúdos.

Mesmo esquema das fotos de diagnóstico: o arquivo vai para o storage local e o
conteúdo guarda a URL. O diretório é trocado por um temporário em cada teste.
"""

import logging
import os
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db import conteudo_queries
from app.db.session import get_db
from app.main import app
from app.models import Conteudo
from app.services import conteudo_storage
from tests.conftest import CenarioAdmin, autenticar_como

pytestmark = pytest.mark.asyncio

UPLOAD = "/api/v1/admin/conteudos/midias"
CONTEUDOS = "/api/v1/admin/conteudos"
AUTH = {"Authorization": "Bearer fake-token"}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def storage_temporario(storage_local_isolado: Path) -> Path:
    pasta = storage_local_isolado / "conteudos"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


@pytest_asyncio.fixture
async def http(cenario_admin: CenarioAdmin) -> AsyncGenerator[AsyncClient]:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(get_db, None)

    async with factory() as db:
        await db.execute(delete(Conteudo).where(Conteudo.criado_por_id == cenario_admin.admin.id))
        await db.commit()
    await engine.dispose()


async def _enviar(http: AsyncClient, dados: bytes = PNG, tipo: str = "image/png"):
    return await http.post(UPLOAD, headers=AUTH, files={"arquivo": ("foto", dados, tipo)})


def _com_midia(url: str, titulo: str = "Com mídia") -> dict:
    return {
        "titulo": titulo,
        "categoria": "higiene",
        "conteudo": {"itens": [{"tipo": "imagem", "url": url, "legenda": "Descrição"}]},
        "destinos": ["home_autenticada"],
        "status": "publicado",
    }


async def test_admin_envia_imagem_e_ela_fica_aberta_para_leitura(http, storage_temporario):
    resposta = await _enviar(http)

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["tipo"] == "imagem"
    assert corpo["url"].startswith("/api/v1/public/conteudos/midias/")
    assert corpo["url"].endswith(".png")
    assert len(list(storage_temporario.iterdir())) == 1

    # Sem login: <img> e <video> do app carregam sem token.
    leitura = await http.get(corpo["url"])
    assert leitura.status_code == 200
    assert leitura.content == PNG


async def test_video_e_aceito_e_atende_pedido_por_faixa(http):
    url = (await _enviar(http, b"0123456789" * 10, "video/mp4")).json()["url"]

    faixa = await http.get(url, headers={"Range": "bytes=0-9"})

    assert faixa.status_code == 206
    assert faixa.content == b"0123456789"


@pytest.mark.parametrize(
    ("dados", "tipo"),
    [(PNG, "application/pdf"), (b"", "image/png")],
)
async def test_formato_nao_aceito_ou_arquivo_vazio_da_400(http, dados, tipo, storage_temporario):
    resposta = await _enviar(http, dados, tipo)

    assert resposta.status_code == 400
    assert resposta.json()["motivo"]
    assert list(storage_temporario.iterdir()) == []


async def test_acima_do_limite_da_413(http, monkeypatch):
    monkeypatch.setattr(conteudo_storage, "MAX_IMAGEM_BYTES", 10)

    assert (await _enviar(http)).status_code == 413


async def test_so_admin_envia(http, cenario_admin):
    autenticar_como(cenario_admin.profissional)
    assert (await _enviar(http)).status_code == 403

    assert (await http.post(UPLOAD, files={"arquivo": ("f", PNG, "image/png")})).status_code == 401


async def test_leitura_de_arquivo_inexistente_ou_fora_da_pasta_da_404(http):
    assert (await http.get("/api/v1/public/conteudos/midias/nao-existe.png")).status_code == 404
    assert (await http.get("/api/v1/public/conteudos/midias/..%2F..%2Fsecreto")).status_code == 404


async def test_trocar_a_midia_ou_excluir_o_conteudo_apaga_o_arquivo_antigo(
    http, storage_temporario
):
    primeira = (await _enviar(http)).json()["url"]
    criado = (await http.post(CONTEUDOS, headers=AUTH, json=_com_midia(primeira))).json()

    segunda = (await _enviar(http)).json()["url"]
    atualizado = await http.patch(
        f"{CONTEUDOS}/{criado['id']}",
        headers=AUTH,
        json={"conteudo": _com_midia(segunda)["conteudo"]},
    )
    assert atualizado.status_code == 200
    assert {p.name for p in storage_temporario.iterdir()} == {segunda.rsplit("/", 1)[1]}

    assert (await http.delete(f"{CONTEUDOS}/{criado['id']}", headers=AUTH)).status_code == 204
    assert list(storage_temporario.iterdir()) == []


async def test_arquivo_usado_por_outro_conteudo_nao_e_apagado(http, storage_temporario):
    url = (await _enviar(http)).json()["url"]
    um = (await http.post(CONTEUDOS, headers=AUTH, json=_com_midia(url, "Um"))).json()
    await http.post(CONTEUDOS, headers=AUTH, json=_com_midia(url, "Dois"))

    assert (await http.delete(f"{CONTEUDOS}/{um['id']}", headers=AUTH)).status_code == 204

    assert len(list(storage_temporario.iterdir())) == 1
    assert (await http.get(url)).status_code == 200


def _nome(url: str) -> str:
    return url.rsplit("/", 1)[1]


async def test_falha_do_storage_depois_do_commit_nao_vira_erro(
    http, storage_temporario, monkeypatch, caplog
):
    primeira = (await _enviar(http)).json()["url"]
    criado = (await http.post(CONTEUDOS, headers=AUTH, json=_com_midia(primeira))).json()
    segunda = (await _enviar(http)).json()["url"]

    async def storage_fora(_nome_arquivo: str) -> None:
        raise OSError("disco indisponível")

    monkeypatch.setattr(conteudo_storage, "remover", storage_fora)
    caplog.set_level(logging.WARNING, logger="app.services.conteudo_service")

    # A alteração foi gravada: a resposta é a de sucesso, mesmo sem apagar o arquivo.
    atualizado = await http.patch(
        f"{CONTEUDOS}/{criado['id']}",
        headers=AUTH,
        json={"conteudo": _com_midia(segunda)["conteudo"]},
    )
    assert atualizado.status_code == 200
    assert atualizado.json()["conteudo"]["itens"][0]["url"] == segunda
    assert (await http.delete(f"{CONTEUDOS}/{criado['id']}", headers=AUTH)).status_code == 204

    # Os arquivos ficaram para a varredura, e a falha foi registrada com o nome.
    assert {p.name for p in storage_temporario.iterdir()} == {_nome(primeira), _nome(segunda)}
    assert _nome(primeira) in caplog.text


async def test_falha_na_consulta_depois_do_commit_nao_vira_erro(http, monkeypatch):
    url = (await _enviar(http)).json()["url"]
    criado = (await http.post(CONTEUDOS, headers=AUTH, json=_com_midia(url))).json()

    async def banco_fora(_db, _nome_arquivo: str) -> bool:
        raise RuntimeError("conexão perdida")

    monkeypatch.setattr(conteudo_queries, "midia_em_uso", banco_fora)

    assert (await http.delete(f"{CONTEUDOS}/{criado['id']}", headers=AUTH)).status_code == 204
    assert (await http.get(f"{CONTEUDOS}/{criado['id']}", headers=AUTH)).status_code == 404


async def test_varredura_no_upload_apaga_so_orfao_antigo(http, storage_temporario):
    orfao_antigo = _nome((await _enviar(http)).json()["url"])
    orfao_recente = _nome((await _enviar(http)).json()["url"])
    em_uso = (await _enviar(http)).json()["url"]
    await http.post(CONTEUDOS, headers=AUTH, json=_com_midia(em_uso))

    dois_dias_atras = time.time() - 2 * 24 * 60 * 60
    for nome in (orfao_antigo, _nome(em_uso)):
        os.utime(storage_temporario / nome, (dois_dias_atras, dois_dias_atras))

    novo = _nome((await _enviar(http)).json()["url"])

    assert {p.name for p in storage_temporario.iterdir()} == {
        orfao_recente,
        _nome(em_uso),
        novo,
    }


UPLOAD_DIRETO = "/api/v1/admin/conteudos/midias/upload"
PUBLICA = "/api/v1/public/conteudos/midias/"


async def _alvo(http: AsyncClient, tipo: str = "image/png", tamanho: int = len(PNG)):
    return await http.post(
        UPLOAD_DIRETO, headers=AUTH, json={"content_type": tipo, "tamanho": tamanho}
    )


async def _enviar_ao_alvo(
    http: AsyncClient, alvo: dict, dados: bytes = PNG, tipo: str = "image/png"
):
    return await http.post(alvo["url"], data=alvo["fields"], files={"file": ("m", dados, tipo)})


@pytest.mark.parametrize(
    ("tipo", "esperado", "extensao"),
    [("image/png", "imagem", ".png"), ("video/mp4", "video", ".mp4")],
)
async def test_alvo_de_midia_e_envio_direto(http, storage_temporario, tipo, esperado, extensao):
    resposta = await _alvo(http, tipo)

    assert resposta.status_code == 200
    alvo = resposta.json()
    assert alvo["tipo"] == esperado
    assert alvo["url"] == "/api/v1/uploads/local"
    assert alvo["fields"]["key"].startswith("conteudos/")
    assert alvo["fields"]["key"].endswith(extensao)
    assert alvo["url_publica"] == PUBLICA + alvo["fields"]["key"].split("/", 1)[1]

    assert (await _enviar_ao_alvo(http, alvo, PNG, tipo)).status_code == 204

    leitura = await http.get(alvo["url_publica"])
    assert leitura.status_code == 200
    assert leitura.content == PNG
    assert len(list(storage_temporario.iterdir())) == 1


@pytest.mark.parametrize(("tipo", "tamanho"), [("application/pdf", 10), ("image/png", 0)])
async def test_alvo_de_midia_recusa_formato_ou_tamanho_vazio(http, tipo, tamanho):
    resposta = await _alvo(http, tipo, tamanho)

    assert resposta.status_code == 400
    assert resposta.json()["motivo"]


@pytest.mark.parametrize(
    ("tipo", "tamanho", "codigo"),
    [
        ("image/png", 10 * 1024 * 1024, 200),
        ("image/png", 10 * 1024 * 1024 + 1, 413),
        ("video/webm", 50 * 1024 * 1024, 200),
        ("video/webm", 50 * 1024 * 1024 + 1, 413),
    ],
)
async def test_alvo_de_midia_respeita_o_limite_do_tipo(http, tipo, tamanho, codigo):
    assert (await _alvo(http, tipo, tamanho)).status_code == codigo


async def test_so_admin_pede_alvo_de_midia(http, cenario_admin):
    autenticar_como(cenario_admin.profissional)

    assert (await _alvo(http)).status_code == 403
    assert (
        await http.post(UPLOAD_DIRETO, json={"content_type": "image/png", "tamanho": 1})
    ).status_code == 401


async def test_varredura_local_apaga_upload_antigo_sem_confirmacao(
    http, storage_temporario, storage_local_isolado
):
    abandonado = (await _alvo(http)).json()
    await _enviar_ao_alvo(http, abandonado)
    recente = (await _alvo(http)).json()
    await _enviar_ao_alvo(http, recente)
    orfao = _nome((await _enviar(http)).json()["url"])
    antigo = time.time() - 2 * 24 * 60 * 60
    for caminho in (
        storage_local_isolado / abandonado["fields"]["key"],
        storage_temporario / orfao,
    ):
        os.utime(caminho, (antigo, antigo))

    await _enviar(http)

    assert not (storage_local_isolado / abandonado["fields"]["key"]).exists()
    assert (storage_local_isolado / recente["fields"]["key"]).exists()
    assert not (storage_temporario / orfao).exists()


async def test_leitura_publica_no_s3_redireciona_para_url_assinada(http, storage_s3_ativo):
    url = (await _enviar(http)).json()["url"]

    resposta = await http.get(url, follow_redirects=False)

    assert resposta.status_code == 302
    assert resposta.headers["cache-control"] == "public, max-age=300"
    destino = urlsplit(resposta.headers["location"])
    assert destino.hostname == "hality-teste.s3.us-east-2.amazonaws.com"
    assert destino.path == f"/conteudos/{_nome(url)}"
    assert parse_qs(destino.query)["X-Amz-Expires"] == ["3600"]
    inexistente = await http.get(PUBLICA + "nao-existe.png", follow_redirects=False)
    assert inexistente.status_code == 404


async def test_alvo_de_midia_no_s3_e_presigned_post(http, storage_s3_ativo):
    alvo = (await _alvo(http, "video/mp4", 1000)).json()

    assert alvo["url"] == "https://hality-teste.s3.us-east-2.amazonaws.com/"
    assert alvo["fields"]["key"].startswith("conteudos/")
    assert alvo["fields"]["Content-Type"] == "video/mp4"
    assert "policy" in alvo["fields"]
    assert alvo["url_publica"].startswith(PUBLICA)
