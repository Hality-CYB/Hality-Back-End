import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

MAX_IMAGE_BYTES = 10 * 1024 * 1024

_STORAGE_DIR = Path(".data/diagnosticos")

_EXTENSOES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


async def salvar(
    conteudo: bytes,
    content_type: str,
    api_prefix: str,
) -> str:
    extensao = _EXTENSOES.get(content_type)

    if extensao is None:
        raise ValueError("content_type não suportado")

    await asyncio.to_thread(
        _STORAGE_DIR.mkdir,
        parents=True,
        exist_ok=True,
    )

    nome_arquivo = f"{uuid4().hex}{extensao}"

    caminho = _STORAGE_DIR / nome_arquivo

    await asyncio.to_thread(
        _gravar_exclusivo,
        caminho,
        conteudo,
    )

    prefixo = api_prefix.rstrip("/")

    return f"{prefixo}/diagnosticos/imagens/{nome_arquivo}"


def _gravar_exclusivo(
    caminho: Path,
    conteudo: bytes,
) -> None:
    with caminho.open("xb") as arquivo:
        arquivo.write(conteudo)


async def calcular_sha256(
    conteudo: bytes,
) -> str:
    return await asyncio.to_thread(
        lambda: hashlib.sha256(conteudo).hexdigest(),
    )


async def ler(
    url_arquivo: str,
) -> bytes:
    """Le um objeto privado sem transformar sua URL em acesso público."""
    nome_arquivo = Path(url_arquivo).name
    caminho = resolver_caminho(nome_arquivo)
    if caminho is None:
        raise FileNotFoundError(nome_arquivo)
    return await asyncio.to_thread(caminho.read_bytes)


async def remover(
    url_arquivo: str,
) -> None:
    nome_arquivo = Path(url_arquivo).name

    caminho = _STORAGE_DIR / nome_arquivo

    await asyncio.to_thread(
        caminho.unlink,
        missing_ok=True,
    )


def resolver_caminho(
    nome_arquivo: str,
) -> Path | None:
    if Path(nome_arquivo).name != nome_arquivo:
        return None

    caminho = _STORAGE_DIR / nome_arquivo

    if not caminho.is_file():
        return None

    return caminho
