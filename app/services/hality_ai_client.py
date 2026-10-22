"""Cliente HTTP da API de inferência (hality-ai).

Fala com o endpoint `POST /analisar`, que recebe a foto da língua (multipart,
campo `foto`) e devolve o veredito de triagem. A API é um classificador de
indício de halitose: não mede saburra nem devolve a classificação de negócio
do back — esse mapeamento fica em `diagnostico_provider`.
"""

from dataclasses import dataclass

import httpx

from app.core.config import get_settings

PROVIDER = "hality-ai"

# Vereditos possíveis devolvidos pela API em `veredito`.
VEREDITO_INDICIO = "indicio"
VEREDITO_SEM_INDICIO = "sem_indicio"
VEREDITO_INCONCLUSIVO = "inconclusivo"
VEREDITO_REJEITADO = "rejeitado"


class HalityAIError(RuntimeError):
    """Falha ao chamar a API ou resposta em formato inesperado."""


class HalityAINaoConfiguradaError(HalityAIError):
    """`HALITY_AI_URL` não definida: não há modelo real para chamar."""


@dataclass(frozen=True)
class ResultadoIA:
    """Resposta de `POST /analisar`, já validada no mínimo necessário."""

    veredito: str
    probabilidade: float | None
    area_lingua: float | None
    nitidez: float | None
    motivo: str
    tempo_ms: int | None

    @property
    def rejeitado(self) -> bool:
        return self.veredito in (VEREDITO_INCONCLUSIVO, VEREDITO_REJEITADO)


async def analisar(
    imagem: bytes,
    content_type: str,
    nome_arquivo: str = "lingua.jpg",
) -> ResultadoIA:
    """Envia a foto para a API e devolve o veredito.

    Levanta `HalityAINaoConfiguradaError` se a URL não estiver definida e
    `HalityAIError` para qualquer falha de rede, status != 2xx ou corpo inválido.
    """
    settings = get_settings()
    base = (settings.hality_ai_url or "").rstrip("/")

    if not base:
        raise HalityAINaoConfiguradaError("HALITY_AI_URL não configurada")

    try:
        async with httpx.AsyncClient(timeout=settings.hality_ai_timeout_seconds) as cliente:
            resposta = await cliente.post(
                f"{base}/analisar",
                files={"foto": (nome_arquivo, imagem, content_type or "image/jpeg")},
            )
    except httpx.HTTPError as exc:
        raise HalityAIError(f"falha de rede ao chamar hality-ai: {exc}") from exc

    if resposta.status_code >= 400:
        raise HalityAIError(f"hality-ai respondeu {resposta.status_code}: {resposta.text[:200]}")

    try:
        corpo = resposta.json()
        veredito = corpo["veredito"]
    except (ValueError, KeyError, TypeError) as exc:
        raise HalityAIError(f"resposta da hality-ai em formato inesperado: {exc}") from exc

    return ResultadoIA(
        veredito=veredito,
        probabilidade=corpo.get("probabilidade"),
        area_lingua=corpo.get("area_lingua"),
        nitidez=corpo.get("nitidez"),
        motivo=corpo.get("motivo") or "",
        tempo_ms=corpo.get("tempo_ms"),
    )
