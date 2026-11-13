"""`POST /uploads/local`: o alvo de upload do storage local (imita o presigned POST)."""

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.api.v1.api import incluir_rotas_de_storage
from app.auth.policies import assinar_policy_upload_local
from app.main import app

pytestmark = pytest.mark.asyncio

ROTA = "/api/v1/uploads/local"
CHAVE = "uploads/0123456789abcdef0123456789abcdef.png"


def _campos(**mudancas: object) -> dict[str, str]:
    base = {"chave": CHAVE, "content_type": "image/png", "max_bytes": 10, "validade": 600}
    base.update(mudancas)
    return assinar_policy_upload_local(**base)  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def http():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def _enviar(http: AsyncClient, campos: dict[str, str], dados: bytes = b"png"):
    return await http.post(ROTA, data=campos, files={"file": ("a.png", dados, "image/png")})


def _arquivos(raiz: Path) -> list[Path]:
    return [p for p in raiz.rglob("*") if p.is_file()]


async def test_envio_valido_grava_o_arquivo(http, storage_local_isolado) -> None:
    resposta = await _enviar(http, _campos())

    assert resposta.status_code == 204
    assert (storage_local_isolado / CHAVE).read_bytes() == b"png"


async def test_nao_precisa_de_login_nem_aceita_outro_alvo(http, storage_local_isolado) -> None:
    campos = _campos()
    campos["key"] = "uploads/ffffffffffffffffffffffffffffffff.png"

    resposta = await _enviar(http, campos)

    assert resposta.status_code == 403
    assert _arquivos(storage_local_isolado) == []


@pytest.mark.parametrize(
    "mudanca",
    [
        {"signature": "0" * 64},
        {"policy": "e30="},
        {"Content-Type": "image/jpeg"},
        {"key": "uploads/ffffffffffffffffffffffffffffffff.png"},
    ],
)
async def test_policy_adulterada_ou_campo_trocado_da_403(http, storage_local_isolado, mudanca):
    campos = {**_campos(), **mudanca}

    resposta = await _enviar(http, campos)

    assert resposta.status_code == 403
    assert _arquivos(storage_local_isolado) == []


async def test_policy_expirada_da_403(http, storage_local_isolado) -> None:
    resposta = await _enviar(http, _campos(validade=-5))

    assert resposta.status_code == 403
    assert _arquivos(storage_local_isolado) == []


async def test_campos_ausentes_da_403(http, storage_local_isolado) -> None:
    resposta = await http.post(ROTA, files={"file": ("a.png", b"x", "image/png")})

    assert resposta.status_code == 403


@pytest.mark.parametrize("dados", [b"", b"x" * 11])
async def test_arquivo_vazio_ou_acima_do_limite_da_400(http, storage_local_isolado, dados) -> None:
    resposta = await _enviar(http, _campos(), dados)

    assert resposta.status_code == 400
    assert resposta.json()["motivo"]
    assert _arquivos(storage_local_isolado) == []


async def test_limite_exato_e_aceito(http, storage_local_isolado) -> None:
    assert (await _enviar(http, _campos(), b"x" * 10)).status_code == 204


async def test_arquivo_ausente_da_400(http, storage_local_isolado) -> None:
    resposta = await http.post(ROTA, data=_campos())

    assert resposta.status_code == 400


async def test_reuso_do_alvo_nao_sobrescreve(http, storage_local_isolado) -> None:
    campos = _campos()
    assert (await _enviar(http, campos, b"um")).status_code == 204

    resposta = await _enviar(http, campos, b"dois")

    assert resposta.status_code == 409
    assert (storage_local_isolado / CHAVE).read_bytes() == b"um"


@pytest.mark.parametrize(("backend", "codigo"), [("local", 403), ("s3", 404)])
def test_rota_so_e_registrada_com_storage_local(backend: str, codigo: int) -> None:
    router = APIRouter()
    incluir_rotas_de_storage(router, backend)
    isolado = FastAPI()
    isolado.include_router(router)

    resposta = TestClient(isolado).post("/uploads/local", files={"file": ("a", b"x", "image/png")})

    assert resposta.status_code == codigo
