"""Imagens e vídeos dos conteúdos (home e orientações).

Mesmo esquema das fotos de diagnóstico (`diagnostico_storage`): o arquivo fica
em `.data/conteudos`, dentro do volume do docker, e o conteúdo guarda só a URL
da rota que o serve. Quando o armazenamento for para o S3 (INFRA-07), a troca é
feita aqui e no `diagnostico_storage`, sem mudar as URLs.
"""

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

MAX_IMAGEM_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024
# O maior dos limites: quanto o endpoint lê do upload antes de validar.
MAX_MIDIA_BYTES = max(MAX_IMAGEM_BYTES, MAX_VIDEO_BYTES)

_STORAGE_DIR = Path(".data/conteudos")

_EXTENSOES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}

ROTA_MIDIAS = "/public/conteudos/midias"


class MidiaInvalidaError(Exception):
    def __init__(self, motivo: str) -> None:
        self.motivo = motivo
        super().__init__(motivo)


class MidiaMuitoGrandeError(Exception):
    pass


def tipo_da_midia(content_type: str) -> str | None:
    """`imagem` ou `video`, ou None quando o formato não é aceito."""
    if content_type not in _EXTENSOES:
        return None

    return "video" if content_type.startswith("video/") else "imagem"


def validar(conteudo: bytes, content_type: str) -> str:
    tipo = tipo_da_midia(content_type)

    if tipo is None:
        raise MidiaInvalidaError(
            "Formato não aceito. Envie imagem JPEG, PNG ou WEBP, ou vídeo MP4 ou WEBM."
        )

    if not conteudo:
        raise MidiaInvalidaError("O arquivo enviado está vazio.")

    limite = MAX_VIDEO_BYTES if tipo == "video" else MAX_IMAGEM_BYTES

    if len(conteudo) > limite:
        raise MidiaMuitoGrandeError

    return tipo


async def salvar(
    conteudo: bytes,
    content_type: str,
    api_prefix: str,
) -> str:
    extensao = _EXTENSOES[content_type]

    await asyncio.to_thread(
        _STORAGE_DIR.mkdir,
        parents=True,
        exist_ok=True,
    )

    nome_arquivo = f"{uuid4().hex}{extensao}"

    await asyncio.to_thread(
        _gravar_exclusivo,
        _STORAGE_DIR / nome_arquivo,
        conteudo,
    )

    return f"{api_prefix.rstrip('/')}{ROTA_MIDIAS}/{nome_arquivo}"


def _gravar_exclusivo(
    caminho: Path,
    conteudo: bytes,
) -> None:
    with caminho.open("xb") as arquivo:
        arquivo.write(conteudo)


def nome_do_arquivo(url: str) -> str | None:
    """Nome do arquivo quando a URL é de uma mídia servida por esta API."""
    marcador = f"{ROTA_MIDIAS}/"

    if marcador not in url:
        return None

    nome = url.rsplit(marcador, 1)[1]

    return nome if Path(nome).name == nome and nome else None


def nomes_no_conteudo(conteudo: dict[str, Any] | None) -> set[str]:
    """Arquivos desta API referenciados pelos blocos de um conteúdo."""
    nomes: set[str] = set()

    for bloco in (conteudo or {}).get("itens", []):
        url = bloco.get("url") if isinstance(bloco, dict) else None

        if isinstance(url, str) and (nome := nome_do_arquivo(url)):
            nomes.add(nome)

    return nomes


async def remover(nome_arquivo: str) -> None:
    if Path(nome_arquivo).name != nome_arquivo:
        return

    await asyncio.to_thread(
        (_STORAGE_DIR / nome_arquivo).unlink,
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
