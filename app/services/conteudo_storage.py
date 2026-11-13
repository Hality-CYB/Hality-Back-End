"""Imagens e vídeos dos conteúdos (home e orientações).

O arquivo fica no storage (`local` ou `s3`, ver `app.services.storage`) sob
`conteudos/` e o conteúdo guarda só a URL da rota que o serve.
"""

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services import storage
from app.services.storage import AlvoDeUpload, ArquivoLocal, UrlAssinada

MAX_IMAGEM_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024
# O maior dos limites: quanto o endpoint lê do upload antes de validar.
MAX_MIDIA_BYTES = max(MAX_IMAGEM_BYTES, MAX_VIDEO_BYTES)

UPLOAD_VALIDADE_SEGUNDOS = 15 * 60

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
    nome_arquivo = f"{uuid4().hex}{extensao}"

    await storage.atual().salvar(f"conteudos/{nome_arquivo}", conteudo, content_type)

    return url_publica(nome_arquivo, api_prefix)


def url_publica(nome_arquivo: str, api_prefix: str) -> str:
    return f"{api_prefix.rstrip('/')}{ROTA_MIDIAS}/{nome_arquivo}"


def validar_declarado(content_type: str, tamanho: int) -> str:
    """Valida formato e tamanho informados antes do envio direto."""
    tipo = tipo_da_midia(content_type)

    if tipo is None or tamanho <= 0:
        # Reaproveita as mensagens de `validar`.
        return validar(b"x" if tamanho > 0 else b"", content_type)

    if tamanho > _limite(tipo):
        raise MidiaMuitoGrandeError

    return tipo


def _limite(tipo: str) -> int:
    return MAX_VIDEO_BYTES if tipo == "video" else MAX_IMAGEM_BYTES


async def preparar_upload(
    content_type: str, tamanho: int, api_prefix: str
) -> tuple[str, AlvoDeUpload, str]:
    """Alvo de envio direto: `(tipo, alvo, url_publica)`."""
    tipo = validar_declarado(content_type, tamanho)
    nome_arquivo = f"{uuid4().hex}{_EXTENSOES[content_type]}"
    alvo = await storage.atual().alvo_de_upload(
        f"conteudos/{nome_arquivo}", content_type, _limite(tipo), UPLOAD_VALIDADE_SEGUNDOS
    )

    return tipo, alvo, url_publica(nome_arquivo, api_prefix)


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


async def arquivos_anteriores_a(limite: datetime) -> list[str]:
    """Nomes dos arquivos gravados antes de `limite` (data de modificação)."""
    chaves = await storage.atual().listar_anteriores_a("conteudos", limite)

    return [Path(chave).name for chave in chaves]


async def uploads_anteriores_a(limite: datetime) -> list[str]:
    """Chaves em `uploads/` antes de `limite`. Só o `local` precisa varrer: no
    `s3` o lifecycle do bucket expira `uploads/` sozinho."""
    return await storage.atual().listar_anteriores_a("uploads", limite)


async def remover_chave(chave: str) -> None:
    await storage.atual().remover(chave)


async def remover(nome_arquivo: str) -> None:
    if Path(nome_arquivo).name != nome_arquivo:
        return

    await storage.atual().remover(f"conteudos/{nome_arquivo}")


async def leitura(nome_arquivo: str, validade: int) -> ArquivoLocal | UrlAssinada | None:
    try:
        return await storage.atual().leitura(f"conteudos/{nome_arquivo}", validade)
    except ValueError:
        return None
