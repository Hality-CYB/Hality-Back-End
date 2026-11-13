"""Adaptadores do storage: `local` no disco e `s3` simulado com moto."""

import base64
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import boto3
import pytest

from app.services import storage
from app.services.storage import (
    ObjetoJaExisteError,
    ObjetoNaoEncontradoError,
    StorageLocal,
)
from tests.conftest import BUCKET_S3 as BUCKET
from tests.conftest import REGIAO_S3 as REGIAO

FUTURO = datetime.now(UTC) + timedelta(days=1)

pytestmark = pytest.mark.asyncio


@pytest.fixture(params=["local", "s3"])
def adaptador(request: pytest.FixtureRequest, storage_local_isolado):
    if request.param == "local":
        return StorageLocal()
    return request.getfixturevalue("s3")


async def test_salvar_ler_metadados_e_remover(adaptador) -> None:
    chave = "diagnosticos/a.png"

    assert await adaptador.metadados(chave) is None
    await adaptador.salvar(chave, b"abc", "image/png")

    assert await adaptador.ler(chave) == b"abc"
    meta = await adaptador.metadados(chave)
    assert meta is not None
    assert meta.tamanho == 3
    await adaptador.remover(chave)
    await adaptador.remover(chave)
    assert await adaptador.metadados(chave) is None


async def test_ler_chave_inexistente(adaptador) -> None:
    with pytest.raises(ObjetoNaoEncontradoError):
        await adaptador.ler("diagnosticos/nao-existe.png")


async def test_salvar_nao_sobrescreve_o_original(adaptador) -> None:
    await adaptador.salvar("diagnosticos/a.png", b"original", "image/png")

    with pytest.raises(ObjetoJaExisteError):
        await adaptador.salvar("diagnosticos/a.png", b"outra", "image/png")

    assert await adaptador.ler("diagnosticos/a.png") == b"original"


async def test_mover_troca_a_origem_pelo_destino(adaptador) -> None:
    await adaptador.salvar("uploads/a.png", b"abc", "image/png")

    await adaptador.mover("uploads/a.png", "diagnosticos/a.png")

    assert await adaptador.ler("diagnosticos/a.png") == b"abc"
    assert await adaptador.metadados("uploads/a.png") is None


async def test_mover_recusa_destino_existente_e_origem_ausente(adaptador) -> None:
    await adaptador.salvar("uploads/a.png", b"novo", "image/png")
    await adaptador.salvar("diagnosticos/a.png", b"original", "image/png")

    with pytest.raises(ObjetoJaExisteError):
        await adaptador.mover("uploads/a.png", "diagnosticos/a.png")
    with pytest.raises(ObjetoNaoEncontradoError):
        await adaptador.mover("uploads/nao-existe.png", "diagnosticos/b.png")

    assert await adaptador.ler("diagnosticos/a.png") == b"original"


async def test_listar_anteriores_a_respeita_prefixo_e_data(adaptador) -> None:
    await adaptador.salvar("conteudos/a.png", b"1", "image/png")
    await adaptador.salvar("conteudos/b.mp4", b"2", "video/mp4")
    await adaptador.salvar("diagnosticos/c.png", b"3", "image/png")

    antigos = await adaptador.listar_anteriores_a("conteudos", FUTURO)
    recentes = await adaptador.listar_anteriores_a(
        "conteudos", datetime.now(UTC) - timedelta(days=1)
    )

    assert sorted(antigos) == ["conteudos/a.png", "conteudos/b.mp4"]
    assert recentes == []
    assert await adaptador.listar_anteriores_a("uploads", FUTURO) == []


@pytest.mark.parametrize(
    "chave", ["../x.png", "outro/a.png", "diagnosticos/../a.png", "diagnosticos/a/b.png", "a.png"]
)
async def test_chave_invalida_e_recusada(adaptador, chave) -> None:
    with pytest.raises(ValueError, match="chave"):
        await adaptador.salvar(chave, b"x", "image/png")


def _policy(alvo) -> dict:
    return json.loads(base64.b64decode(alvo.fields["policy"]))


async def test_s3_alvo_de_upload_forca_chave_tipo_e_tamanho(s3) -> None:
    alvo = await s3.alvo_de_upload("uploads/a.png", "image/png", 1234, 900)

    assert alvo.url == f"https://{BUCKET}.s3.{REGIAO}.amazonaws.com/"
    assert alvo.fields["key"] == "uploads/a.png"
    assert alvo.fields["Content-Type"] == "image/png"
    assert alvo.fields["x-amz-algorithm"] == "AWS4-HMAC-SHA256"
    assert REGIAO in alvo.fields["x-amz-credential"]
    condicoes = _policy(alvo)["conditions"]
    assert {"bucket": BUCKET} in condicoes
    assert {"key": "uploads/a.png"} in condicoes
    assert {"Content-Type": "image/png"} in condicoes
    assert ["content-length-range", 1, 1234] in condicoes
    expira = datetime.fromisoformat(_policy(alvo)["expiration"].replace("Z", "+00:00"))
    assert timedelta(minutes=14) < expira - datetime.now(UTC) <= timedelta(minutes=15)


async def test_s3_envio_pelo_alvo_grava_o_objeto(s3) -> None:
    import requests

    alvo = await s3.alvo_de_upload("uploads/a.png", "image/png", 1234, 900)

    resposta = requests.post(alvo.url, data=alvo.fields, files={"file": ("a.png", b"png")})

    assert resposta.status_code in (200, 201, 204)
    assert await s3.ler("uploads/a.png") == b"png"
    cliente = boto3.client("s3", region_name=REGIAO)
    assert cliente.head_object(Bucket=BUCKET, Key="uploads/a.png")["ContentType"] == "image/png"


async def test_s3_leitura_devolve_url_assinada_curta(s3) -> None:
    await s3.salvar("diagnosticos/a.png", b"abc", "image/png")

    leitura = await s3.leitura("diagnosticos/a.png", 300)

    assert isinstance(leitura, storage.UrlAssinada)
    partes = urlsplit(leitura.url)
    consulta = parse_qs(partes.query)
    assert partes.hostname == f"{BUCKET}.s3.{REGIAO}.amazonaws.com"
    assert partes.path == "/diagnosticos/a.png"
    assert consulta["X-Amz-Expires"] == ["300"]
    assert consulta["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert await s3.leitura("diagnosticos/nao-existe.png", 300) is None


async def test_local_alvo_de_upload_assina_a_policy(storage_local_isolado) -> None:
    alvo = await StorageLocal().alvo_de_upload("uploads/a.png", "image/png", 99, 900)

    assert alvo.url == "/api/v1/uploads/local"
    assert set(alvo.fields) == {"key", "Content-Type", "policy", "signature"}
    assert alvo.fields["key"] == "uploads/a.png"


async def test_local_leitura_devolve_arquivo(storage_local_isolado) -> None:
    await StorageLocal().salvar("conteudos/a.png", b"abc", "image/png")

    leitura = await StorageLocal().leitura("conteudos/a.png", 300)

    assert isinstance(leitura, storage.ArquivoLocal)
    assert leitura.caminho.read_bytes() == b"abc"
    assert await StorageLocal().leitura("conteudos/b.png", 300) is None


async def test_ler_privado_le_do_s3_pela_url_do_arquivo(storage_s3_ativo) -> None:
    from app.services import diagnostico_storage

    url = await diagnostico_storage.salvar(b"original", "image/png", "/api/v1")

    assert await diagnostico_storage.ler_privado(url) == b"original"
    with pytest.raises(FileNotFoundError):
        await diagnostico_storage.ler_privado("/api/v1/diagnosticos/imagens/sumiu.png")
    with pytest.raises(FileNotFoundError):
        await diagnostico_storage.ler_privado("/api/v1/diagnosticos/imagens/..%2Fx")
