"""Fluxo novo da foto do diagnóstico: alvo de upload, envio direto e confirmação.

Roda com o storage `local`, em que o alvo aponta para `POST /uploads/local`
(mesmo contrato do presigned POST do S3).
"""

import hashlib
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import boto3
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.policies import assinar_upload_token
from app.auth.users import current_active_user
from app.db import diagnostico_queries
from app.db.session import get_db
from app.main import app
from app.models.user import User
from tests.test_diagnostico import (
    AUTH_HEADERS,
    JPEG_MINIMO,
    PACIENTE_STUB_ID,
    _contar_diagnosticos_da_anamnese,
    _criar_anamnese_do_paciente_stub,
    _imagens_da_anamnese,
    _limpar_consentimento_e_anamnese,
    _registrar_decisao_de_tratamento,
    client,
)

ALVO = "/api/v1/diagnosticos/upload"
DIAGNOSTICOS = "/api/v1/diagnosticos"


@pytest.fixture
def anamnese_id():
    anamnese = _criar_anamnese_do_paciente_stub()
    yield anamnese
    _limpar_consentimento_e_anamnese([], anamnese)


def _arquivos(raiz: Path, pasta: str) -> list[Path]:
    destino = raiz / pasta
    return sorted(destino.iterdir()) if destino.is_dir() else []


def _pedir_alvo(anamnese: int, content_type: str = "image/jpeg"):
    return client.post(
        ALVO,
        headers=AUTH_HEADERS,
        json={"anamnese_id": anamnese, "content_type": content_type},
    )


def _enviar_ao_alvo(alvo: dict[str, Any], dados: bytes = JPEG_MINIMO, tipo: str = "image/jpeg"):
    return client.post(alvo["url"], data=alvo["fields"], files={"file": ("foto", dados, tipo)})


def _confirmar(anamnese: int, token: str):
    return client.post(
        DIAGNOSTICOS,
        headers=AUTH_HEADERS,
        json={"anamnese_id": anamnese, "upload_token": token, "parametros_captura": {"a": 1}},
    )


def test_fluxo_completo_grava_como_o_multipart(anamnese_id, storage_local_isolado) -> None:
    alvo = _pedir_alvo(anamnese_id)
    assert alvo.status_code == 200
    corpo = alvo.json()
    assert corpo["url"] == "/api/v1/uploads/local"
    assert corpo["fields"]["key"].startswith("uploads/")
    assert corpo["fields"]["key"].endswith(".jpg")

    assert _enviar_ao_alvo(corpo).status_code == 204
    assert len(_arquivos(storage_local_isolado, "uploads")) == 1

    criado = _confirmar(anamnese_id, corpo["upload_token"])

    assert criado.status_code == 202
    assert criado.json()["anamnese_id"] == anamnese_id
    imagem = _imagens_da_anamnese(anamnese_id)[0]
    assert imagem.sha256 == hashlib.sha256(JPEG_MINIMO).hexdigest()
    assert imagem.tamanho_bytes == len(JPEG_MINIMO)
    assert imagem.content_type == "image/jpeg"
    assert imagem.url_arquivo.startswith("/api/v1/diagnosticos/imagens/")
    assert imagem.parametros_captura == {"a": 1}
    assert [p.name for p in _arquivos(storage_local_isolado, "diagnosticos")] == [
        imagem.url_arquivo.rsplit("/", 1)[1]
    ]
    assert _arquivos(storage_local_isolado, "uploads") == []

    detalhe = client.get(f"{DIAGNOSTICOS}/{criado.json()['id']}", headers=AUTH_HEADERS).json()
    leitura = client.get(detalhe["imagens"][0]["url_arquivo"])
    assert leitura.status_code == 200
    assert leitura.content == JPEG_MINIMO


def test_alvo_com_usuario_orm_da_sessao_da_request(anamnese_id, storage_local_isolado) -> None:
    """Como em produção: o usuário é um `User` ORM da mesma sessão da request.

    O rollback que solta o lock da anamnese expira o usuário; ler `usuario.id`
    depois dele estourava `MissingGreenlet` (500). A suíte usa um stub que não é
    ORM, então esse caminho precisa de um usuário carregado pela sessão.
    """

    async def usuario_da_sessao(db: AsyncSession = Depends(get_db)) -> User:  # noqa: B008
        usuario = await db.get(User, PACIENTE_STUB_ID)
        assert usuario is not None
        return usuario

    anterior = app.dependency_overrides[current_active_user]
    app.dependency_overrides[current_active_user] = usuario_da_sessao
    try:
        alvo = _pedir_alvo(anamnese_id)
        assert alvo.status_code == 200
        corpo = alvo.json()
        assert set(corpo) == {"url", "fields", "upload_token"}

        assert _enviar_ao_alvo(corpo).status_code == 204
        assert _confirmar(anamnese_id, corpo["upload_token"]).status_code == 202
    finally:
        app.dependency_overrides[current_active_user] = anterior


def test_alvo_recusa_anamnese_inexistente() -> None:
    assert _pedir_alvo(2_000_000_000).status_code == 404


def test_alvo_recusa_formato_invalido(anamnese_id) -> None:
    resposta = _pedir_alvo(anamnese_id, "image/gif")

    assert resposta.status_code == 400
    assert resposta.json()["motivo"] == "Formato de imagem inválido. Envie JPEG, PNG ou WEBP."


def test_alvo_recusa_sem_consentimento_vigente(anamnese_id) -> None:
    eventos = [
        _registrar_decisao_de_tratamento(aceito=True),
        _registrar_decisao_de_tratamento(aceito=False),
    ]
    try:
        assert _pedir_alvo(anamnese_id).status_code == 403
    finally:
        _limpar_consentimento_e_anamnese(eventos, anamnese_id)


def test_alvo_de_anamnese_ja_usada_devolve_409_com_diagnostico(anamnese_id) -> None:
    alvo = _pedir_alvo(anamnese_id).json()
    _enviar_ao_alvo(alvo)
    criado = _confirmar(anamnese_id, alvo["upload_token"]).json()

    resposta = _pedir_alvo(anamnese_id)

    assert resposta.status_code == 409
    assert resposta.json()["diagnostico_id"] == criado["id"]
    assert resposta.json()["status"] == "processando"


def test_409_na_confirmacao_remove_o_upload(anamnese_id, storage_local_isolado) -> None:
    a = _pedir_alvo(anamnese_id).json()
    b = _pedir_alvo(anamnese_id).json()
    _enviar_ao_alvo(a)
    _enviar_ao_alvo(b)
    assert _confirmar(anamnese_id, a["upload_token"]).status_code == 202
    assert len(_arquivos(storage_local_isolado, "uploads")) == 1

    resposta = _confirmar(anamnese_id, b["upload_token"])

    assert resposta.status_code == 409
    assert "diagnostico_id" in resposta.json()
    assert _arquivos(storage_local_isolado, "uploads") == []
    assert len(_arquivos(storage_local_isolado, "diagnosticos")) == 1


def test_token_adulterado_e_recusado(anamnese_id, storage_local_isolado) -> None:
    alvo = _pedir_alvo(anamnese_id).json()
    _enviar_ao_alvo(alvo)
    carga, _, assinatura = alvo["upload_token"].partition(".")

    for token in (f"{carga}.{'0' * len(assinatura)}", f"x{carga}.{assinatura}", "lixo", ""):
        resposta = _confirmar(anamnese_id, token)
        assert resposta.status_code == 400
        assert "inválido ou expirado" in resposta.json()["motivo"]

    assert _contar_diagnosticos_da_anamnese(anamnese_id) == 0
    assert _arquivos(storage_local_isolado, "diagnosticos") == []


@pytest.mark.parametrize(
    "defeito", ["expirado", "outro_usuario", "outra_anamnese", "fora_de_uploads"]
)
def test_token_invalido_e_recusado(anamnese_id, storage_local_isolado, defeito) -> None:
    alvo = _pedir_alvo(anamnese_id).json()
    _enviar_ao_alvo(alvo)
    chave = alvo["fields"]["key"]
    token = assinar_upload_token(
        chave=chave if defeito != "fora_de_uploads" else chave.replace("uploads/", "diagnosticos/"),
        usuario_id=uuid.uuid4() if defeito == "outro_usuario" else PACIENTE_STUB_ID,
        anamnese_id=anamnese_id + 1 if defeito == "outra_anamnese" else anamnese_id,
        content_type="image/jpeg",
        validade=-10 if defeito == "expirado" else 600,
    )

    resposta = _confirmar(anamnese_id, token)

    assert resposta.status_code == 400
    assert _contar_diagnosticos_da_anamnese(anamnese_id) == 0
    assert _arquivos(storage_local_isolado, "diagnosticos") == []


def test_confirmar_sem_ter_enviado_o_arquivo(anamnese_id) -> None:
    alvo = _pedir_alvo(anamnese_id).json()

    resposta = _confirmar(anamnese_id, alvo["upload_token"])

    assert resposta.status_code == 400
    assert "não foi enviada" in resposta.json()["motivo"]
    assert _contar_diagnosticos_da_anamnese(anamnese_id) == 0


def test_falha_no_insert_nao_deixa_arquivo(anamnese_id, storage_local_isolado, monkeypatch):
    async def falha(**_kwargs):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(diagnostico_queries, "inserir", falha)
    alvo = _pedir_alvo(anamnese_id).json()
    _enviar_ao_alvo(alvo)

    with TestClient(app, raise_server_exceptions=False) as seguro:
        resposta = seguro.post(
            DIAGNOSTICOS,
            headers=AUTH_HEADERS,
            json={
                "anamnese_id": anamnese_id,
                "upload_token": alvo["upload_token"],
                "parametros_captura": {},
            },
        )

    assert resposta.status_code == 500
    assert _arquivos(storage_local_isolado, "diagnosticos") == []
    assert _arquivos(storage_local_isolado, "uploads") == []


def test_confirmacao_json_exige_os_campos(anamnese_id) -> None:
    resposta = client.post(DIAGNOSTICOS, headers=AUTH_HEADERS, json={"anamnese_id": anamnese_id})

    assert resposta.status_code == 422


def test_content_type_desconhecido_no_post_da_415() -> None:
    resposta = client.post(DIAGNOSTICOS, headers=AUTH_HEADERS, content=b"x")

    assert resposta.status_code == 415


def test_multipart_antigo_continua_aceito(anamnese_id, storage_local_isolado) -> None:
    resposta = client.post(
        DIAGNOSTICOS,
        headers=AUTH_HEADERS,
        data={"anamnese_id": str(anamnese_id), "parametros_captura": "{}"},
        files={"imagem": ("lingua.jpg", JPEG_MINIMO, "image/jpeg")},
    )

    assert resposta.status_code == 202
    assert len(_arquivos(storage_local_isolado, "diagnosticos")) == 1
    assert _arquivos(storage_local_isolado, "uploads") == []


@pytest.mark.parametrize(
    ("data", "files", "codigo"),
    [
        ({"parametros_captura": "{}"}, {"imagem": ("a.jpg", JPEG_MINIMO, "image/jpeg")}, 422),
        (
            {"anamnese_id": "x", "parametros_captura": "{}"},
            {"imagem": ("a", b"x", "image/jpeg")},
            422,
        ),
        (
            {"anamnese_id": "1", "parametros_captura": "{}"},
            {"outro": ("a", b"x", "image/jpeg")},
            422,
        ),
        ({"anamnese_id": "1"}, {"imagem": ("a", b"x", "image/jpeg")}, 422),
    ],
)
def test_multipart_antigo_mantem_a_validacao(data, files, codigo) -> None:
    resposta = client.post(DIAGNOSTICOS, headers=AUTH_HEADERS, data=data, files=files)

    assert resposta.status_code == codigo


def test_fluxo_completo_no_s3_e_leitura_com_redirect(anamnese_id, storage_s3_ativo) -> None:
    import requests

    alvo = _pedir_alvo(anamnese_id).json()
    assert alvo["url"] == "https://hality-teste.s3.us-east-2.amazonaws.com/"
    assert requests.post(alvo["url"], data=alvo["fields"], files={"file": JPEG_MINIMO}).ok

    criado = _confirmar(anamnese_id, alvo["upload_token"])

    assert criado.status_code == 202
    imagem = _imagens_da_anamnese(anamnese_id)[0]
    nome = imagem.url_arquivo.rsplit("/", 1)[1]
    cliente = boto3.client("s3", region_name="us-east-2")
    chaves = [o["Key"] for o in cliente.list_objects_v2(Bucket="hality-teste")["Contents"]]
    assert chaves == [f"diagnosticos/{nome}"]
    assert imagem.sha256 == hashlib.sha256(JPEG_MINIMO).hexdigest()

    detalhe = client.get(f"{DIAGNOSTICOS}/{criado.json()['id']}", headers=AUTH_HEADERS).json()
    por_url = client.get(detalhe["imagens"][0]["url_arquivo"], follow_redirects=False)
    assert por_url.status_code == 302
    assert por_url.headers["cache-control"] == "no-store"
    destino = urlsplit(por_url.headers["location"])
    assert destino.hostname == "hality-teste.s3.us-east-2.amazonaws.com"
    assert destino.path == f"/diagnosticos/{nome}"
    assert parse_qs(destino.query)["X-Amz-Expires"] == ["300"]

    assert client.get(imagem.url_arquivo, follow_redirects=False).status_code == 401
