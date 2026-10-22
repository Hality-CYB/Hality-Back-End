"""Processa o diagnóstico com o modelo real (API hality-ai).

Substitui o `diagnostico_mock` quando `HALITY_AI_URL` está configurada; sem ela,
delega ao mock para o desenvolvimento seguir funcionando sem o modelo.

Mapeamento (decisão de negócio, ajuste aqui): a API devolve um veredito de
indício de halitose + probabilidade, enquanto o back trabalha com uma
classificação ordenada e uma escala de saburra. A tradução está em `_mapear`.
"""

import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.erros_diagnostico import CodigoErroDiagnostico
from app.db import diagnostico_queries
from app.models.diagnostico import Diagnostico
from app.schemas.diagnostico import OrigemResultado, StatusDiagnostico
from app.services import diagnostico_mock, diagnostico_storage, hality_ai_client
from app.services.hality_ai_client import (
    VEREDITO_SEM_INDICIO,
    HalityAIError,
    ResultadoIA,
)

# veredito/probabilidade -> código da classificação cadastrada (ver scripts/seed.py).
CLASSIFICACAO_SEM_INDICIO = "halito_normal"
CLASSIFICACAO_INDICIO_LEVE = "halitose_intima"
CLASSIFICACAO_INDICIO_FORTE = "mau_halito_social"

# Acima deste valor, o indício é classificado como o grau mais alto.
LIMIAR_INDICIO_FORTE = 0.75


@dataclass(frozen=True)
class _Mapeado:
    classificacao_codigo: str
    escala_saburra: int | None
    confianca_ia: float | None


def _mapear(resultado: ResultadoIA) -> _Mapeado:
    """Traduz o veredito da API para os campos de negócio do diagnóstico.

    Só é chamado para vereditos conclusivos (indicio/sem_indicio); os demais
    são tratados como falha antes de chegar aqui.

    `escala_saburra` é derivada da probabilidade como PROXY: a API não mede a
    saburra lingual, então isto é um placeholder até existir essa medida real.
    """
    prob = resultado.probabilidade

    if resultado.veredito == VEREDITO_SEM_INDICIO:
        codigo = CLASSIFICACAO_SEM_INDICIO
    elif prob is not None and prob >= LIMIAR_INDICIO_FORTE:
        codigo = CLASSIFICACAO_INDICIO_FORTE
    else:
        codigo = CLASSIFICACAO_INDICIO_LEVE

    saburra = None if prob is None else round(prob * 100)

    return _Mapeado(
        classificacao_codigo=codigo,
        escala_saburra=saburra,
        confianca_ia=prob,
    )


async def _ler_imagem(
    db: AsyncSession,
    diagnostico: Diagnostico,
) -> tuple[bytes, str] | None:
    """Recupera os bytes e o content_type da imagem do diagnóstico, ou None."""
    imagens = await diagnostico_queries.listar_imagens(db, diagnostico.id)

    if not imagens:
        return None

    imagem = imagens[0]
    nome_arquivo = imagem.url_arquivo.rsplit("/", 1)[-1]
    caminho = diagnostico_storage.resolver_caminho(nome_arquivo)

    if caminho is None:
        return None

    conteudo = await asyncio.to_thread(caminho.read_bytes)

    return conteudo, imagem.content_type or "image/jpeg"


async def processar_se_necessario(
    db: AsyncSession,
    diagnostico: Diagnostico,
) -> Diagnostico:
    """Gera o resultado do diagnóstico ainda em processamento.

    Com `HALITY_AI_URL` definida, chama o modelo real; sem ela, cai no mock.
    Idempotente: diagnóstico fora de 'processando' é devolvido sem tocar na API.
    """
    if diagnostico.status != StatusDiagnostico.PROCESSANDO.value:
        return diagnostico

    if not get_settings().hality_ai_url:
        return await diagnostico_mock.processar_se_necessario(db, diagnostico)

    dados_imagem = await _ler_imagem(db, diagnostico)

    if dados_imagem is None:
        return await diagnostico_queries.marcar_falha(
            db,
            diagnostico,
            origem=OrigemResultado.MODELO,
            erro_codigo=CodigoErroDiagnostico.FALHA_PROCESSAMENTO,
            erro_interno="imagem do diagnóstico não encontrada no storage",
        )

    imagem_bytes, content_type = dados_imagem

    try:
        resultado = await hality_ai_client.analisar(imagem_bytes, content_type)
    except HalityAIError as exc:
        return await diagnostico_queries.marcar_falha(
            db,
            diagnostico,
            origem=OrigemResultado.MODELO,
            erro_codigo=CodigoErroDiagnostico.FALHA_PROCESSAMENTO,
            erro_interno=str(exc),
        )

    # Vereditos inconclusivos/rejeitados não viram resultado: falha com o motivo
    # que a API devolveu (texto de orientação ao usuário) guardado no erro interno.
    if resultado.rejeitado:
        return await diagnostico_queries.marcar_falha(
            db,
            diagnostico,
            origem=OrigemResultado.MODELO,
            erro_codigo=CodigoErroDiagnostico.FALHA_PROCESSAMENTO,
            erro_interno=f"{resultado.veredito}: {resultado.motivo}",
        )

    mapeado = _mapear(resultado)

    classificacao = await diagnostico_queries.buscar_classificacao_por_codigo(
        db,
        mapeado.classificacao_codigo,
    )

    if classificacao is None:
        return await diagnostico_queries.marcar_falha(
            db,
            diagnostico,
            origem=OrigemResultado.MODELO,
            erro_codigo=CodigoErroDiagnostico.CLASSIFICACAO_NAO_CONFIGURADA,
            erro_interno=(
                f"classificação '{mapeado.classificacao_codigo}' não cadastrada"
            ),
        )

    return await diagnostico_queries.concluir_modelo(
        db,
        diagnostico,
        classificacao_id=classificacao.id,
        escala_saburra=mapeado.escala_saburra,
        confianca_ia=mapeado.confianca_ia,
        provider=hality_ai_client.PROVIDER,
        versao=None,
    )
