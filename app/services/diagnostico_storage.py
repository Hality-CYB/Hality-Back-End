import asyncio
import hashlib
from pathlib import PurePosixPath
from uuid import uuid4

from app.services import storage
from app.services.storage import AlvoDeUpload, ArquivoLocal, UrlAssinada

MAX_IMAGE_BYTES = 10 * 1024 * 1024

# Validade do alvo de upload (presigned POST / policy local).
UPLOAD_VALIDADE_SEGUNDOS = 15 * 60

_EXTENSOES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

_CONTENT_TYPES = {extensao: tipo for tipo, extensao in _EXTENSOES.items()}


def formato_aceito(content_type: str) -> bool:
    return content_type in _EXTENSOES


def _nome_da_url(url_arquivo: str) -> str:
    return PurePosixPath(url_arquivo.split("?", 1)[0]).name


def _url_arquivo(nome_arquivo: str, api_prefix: str) -> str:
    return f"{api_prefix.rstrip('/')}/diagnosticos/imagens/{nome_arquivo}"


async def salvar(
    conteudo: bytes,
    content_type: str,
    api_prefix: str,
) -> str:
    extensao = _EXTENSOES.get(content_type)

    if extensao is None:
        raise ValueError("content_type não suportado")

    nome_arquivo = f"{uuid4().hex}{extensao}"

    await storage.atual().salvar(f"diagnosticos/{nome_arquivo}", conteudo, content_type)

    return _url_arquivo(nome_arquivo, api_prefix)


async def preparar_upload(content_type: str) -> tuple[str, AlvoDeUpload]:
    """Chave em `uploads/` e o alvo para o navegador enviar a foto direto."""
    extensao = _EXTENSOES.get(content_type)

    if extensao is None:
        raise ValueError("content_type não suportado")

    chave = f"uploads/{uuid4().hex}{extensao}"
    alvo = await storage.atual().alvo_de_upload(
        chave, content_type, MAX_IMAGE_BYTES, UPLOAD_VALIDADE_SEGUNDOS
    )

    return chave, alvo


async def consolidar_upload(chave_upload: str, api_prefix: str) -> tuple[str, bytes]:
    """Move o upload para `diagnosticos/` e devolve `url_arquivo` e os bytes.

    Move antes de ler: depois disso o navegador não consegue mais trocar o
    arquivo, então o `sha256` calculado é do objeto que fica guardado.
    """
    nome_arquivo = PurePosixPath(chave_upload).name
    destino = f"diagnosticos/{nome_arquivo}"

    await storage.atual().mover(chave_upload, destino)

    try:
        conteudo = await storage.atual().ler(destino)
    except BaseException:
        await storage.atual().remover(destino)
        raise

    return _url_arquivo(nome_arquivo, api_prefix), conteudo


async def remover_upload(chave_upload: str) -> None:
    await storage.atual().remover(chave_upload)


async def calcular_sha256(
    conteudo: bytes,
) -> str:
    return await asyncio.to_thread(
        lambda: hashlib.sha256(conteudo).hexdigest(),
    )


async def ler_privado(url_arquivo: str) -> bytes:
    """Lê um arquivo pelo identificador interno, sem expor URL de storage."""
    try:
        return await storage.atual().ler(f"diagnosticos/{_nome_da_url(url_arquivo)}")
    except ValueError as exc:
        raise FileNotFoundError("imagem não encontrada") from exc


async def remover(
    url_arquivo: str,
) -> None:
    try:
        await storage.atual().remover(f"diagnosticos/{_nome_da_url(url_arquivo)}")
    except ValueError:
        return


async def leitura(nome_arquivo: str, validade: int) -> ArquivoLocal | UrlAssinada | None:
    try:
        return await storage.atual().leitura(f"diagnosticos/{nome_arquivo}", validade)
    except ValueError:
        return None


def content_type_da_extensao(nome_arquivo: str) -> str | None:
    return _CONTENT_TYPES.get(PurePosixPath(nome_arquivo).suffix)
