import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import anamnese_queries, diagnostico_queries
from app.models.diagnostico import Diagnostico
from app.services import diagnostico_storage
from app.services.diagnostic_provider import (
    DiagnosticProviderError,
    DiagnosticRequest,
    get_diagnostic_provider,
    validate_provider_result,
)

AVISO_LEGAL = (
    "Este é um pré-diagnóstico de apoio e não substitui a avaliação de um profissional de saúde."
)

ERRO_PROCESSAMENTO = "Não foi possível processar o diagnóstico."

STATUS_COM_RESULTADO = {
    "aguardando_revisao",
    "concluido",
}


class ImagemInvalidaError(Exception):
    def __init__(self, motivo: str) -> None:
        self.motivo = motivo
        super().__init__(motivo)


class ArquivoMuitoGrandeError(Exception):
    pass


class AnamneseNaoEncontradaError(Exception):
    pass


class AnamneseJaUtilizadaError(Exception):
    pass


class DiagnosticoNaoEncontradoError(Exception):
    pass


class DiagnosticoAcessoNegadoError(Exception):
    pass


class DiagnosticoRetryInvalidoError(Exception):
    pass


def _validar_imagem(
    imagem: bytes,
    content_type: str,
) -> None:
    if not imagem:
        raise ImagemInvalidaError("A imagem enviada está vazia.")

    if len(imagem) > diagnostico_storage.MAX_IMAGE_BYTES:
        raise ArquivoMuitoGrandeError

    if content_type not in {
        "image/jpeg",
        "image/png",
        "image/webp",
    }:
        raise ImagemInvalidaError("Formato de imagem inválido. Envie JPEG, PNG ou WEBP.")


def _normalizar_respostas(respostas: list) -> list:
    return [
        resposta.model_dump(mode="json") if hasattr(resposta, "model_dump") else resposta
        for resposta in respostas
    ]


def _montar_revisao(
    diagnostico: Diagnostico,
    profissional_nome: str | None,
) -> dict[str, Any] | None:
    if diagnostico.status not in STATUS_COM_RESULTADO:
        return None

    revisado = (
        diagnostico.status == "concluido"
        and diagnostico.profissional_revisor_id is not None
        and diagnostico.data_revisao is not None
    )

    return {
        "revisado": revisado,
        "profissional_nome": (profissional_nome if revisado else None),
        "data_revisao": (diagnostico.data_revisao if revisado else None),
        "observacoes": (diagnostico.observacoes_revisao if revisado else None),
        "nivel_corrigido": (
            getattr(
                diagnostico,
                "nivel_corrigido",
                False,
            )
            if revisado
            else False
        ),
    }


async def _processar_com_provider(
    db: AsyncSession,
    diagnostico: Diagnostico,
    anamnese: Any,
    url_arquivo: str,
) -> Diagnostico:
    settings = get_settings()
    provider = get_diagnostic_provider(settings)

    request = DiagnosticRequest(
        evaluation_id=diagnostico.id,
        image_reference=url_arquivo,
        anamnesis_answers=_normalizar_respostas(anamnese.respostas),
    )

    try:
        resultado = await provider.analyze(request)
        validate_provider_result(resultado)

    except DiagnosticProviderError:
        return await diagnostico_queries.marcar_falha(
            db=db,
            diagnostico=diagnostico,
            erro=ERRO_PROCESSAMENTO,
            provider=settings.diagnostic_provider,
            model_version="unknown",
            data_processamento=datetime.now(UTC),
        )

    if resultado.status == "processing":
        return await diagnostico_queries.marcar_processando(
            db=db,
            diagnostico=diagnostico,
            provider=resultado.provider,
            model_version=resultado.model_version,
        )

    if resultado.status == "failed":
        return await diagnostico_queries.marcar_falha(
            db=db,
            diagnostico=diagnostico,
            erro=ERRO_PROCESSAMENTO,
            provider=resultado.provider,
            model_version=resultado.model_version,
            data_processamento=resultado.processed_at or datetime.now(UTC),
        )

    classificacao = await diagnostico_queries.buscar_classificacao_por_ordem(
        db,
        resultado.level,
    )

    if classificacao is None:
        return await diagnostico_queries.marcar_falha(
            db=db,
            diagnostico=diagnostico,
            erro=ERRO_PROCESSAMENTO,
            provider=resultado.provider,
            model_version=resultado.model_version,
            data_processamento=resultado.processed_at or datetime.now(UTC),
        )

    return await diagnostico_queries.salvar_resultado(
        db=db,
        diagnostico=diagnostico,
        classificacao_id=classificacao.id,
        provider=resultado.provider,
        model_version=resultado.model_version,
        score=resultado.score,
        confianca_ia=resultado.confidence,
        data_processamento=resultado.processed_at or datetime.now(UTC),
    )


async def criar_diagnostico(
    db: AsyncSession,
    paciente_id: uuid.UUID,
    anamnese_id: int,
    imagem: bytes,
    content_type: str,
    parametros_captura: dict[str, Any],
) -> dict[str, Any]:
    anamnese = await anamnese_queries.buscar_por_id(
        db,
        anamnese_id,
    )

    if anamnese is None or anamnese.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError

    existente = await diagnostico_queries.buscar_por_anamnese(
        db,
        anamnese_id,
    )

    if existente is not None:
        raise AnamneseJaUtilizadaError

    _validar_imagem(
        imagem,
        content_type,
    )

    url_arquivo = await diagnostico_storage.salvar(
        imagem,
        content_type,
        get_settings().api_v1_prefix,
    )

    try:
        diagnostico = await diagnostico_queries.inserir(
            db=db,
            paciente_id=paciente_id,
            anamnese_id=anamnese_id,
            url_arquivo=url_arquivo,
            parametros_captura=parametros_captura,
        )

    except IntegrityError as exc:
        await db.rollback()
        await diagnostico_storage.remover(url_arquivo)

        existente = await diagnostico_queries.buscar_por_anamnese(
            db,
            anamnese_id,
        )

        if existente is not None:
            raise AnamneseJaUtilizadaError from exc

        raise

    except Exception:
        await db.rollback()
        await diagnostico_storage.remover(url_arquivo)
        raise

    diagnostico = await _processar_com_provider(
        db=db,
        diagnostico=diagnostico,
        anamnese=anamnese,
        url_arquivo=url_arquivo,
    )

    return {
        "id": diagnostico.id,
        "status": diagnostico.status,
        "data_diagnostico": diagnostico.data_diagnostico,
        "anamnese_id": anamnese_id,
    }


async def obter_diagnostico(
    db: AsyncSession,
    paciente_id: uuid.UUID,
    diagnostico_id: int,
) -> dict[str, Any]:
    diagnostico = await diagnostico_queries.buscar_por_id(
        db,
        diagnostico_id,
    )

    if diagnostico is None:
        raise DiagnosticoNaoEncontradoError

    if diagnostico.paciente_id != paciente_id:
        raise DiagnosticoAcessoNegadoError

    if diagnostico.anamnese_id is None:
        raise AnamneseNaoEncontradaError

    anamnese = await anamnese_queries.buscar_por_id(
        db,
        diagnostico.anamnese_id,
    )

    if anamnese is None:
        raise AnamneseNaoEncontradaError

    dados = await diagnostico_queries.buscar_dados_detalhe(
        db,
        diagnostico,
    )

    tem_resultado = diagnostico.status in STATUS_COM_RESULTADO

    classificacao = dados.classificacao if tem_resultado else None

    revisao = _montar_revisao(
        diagnostico,
        dados.profissional_nome,
    )

    return {
        "id": diagnostico.id,
        "data_diagnostico": diagnostico.data_diagnostico,
        "status": diagnostico.status,
        "classificacao": (
            {
                "id": classificacao.id,
                "codigo": classificacao.codigo,
                "nome_exibicao": classificacao.nome_exibicao,
                "ordem": classificacao.ordem,
            }
            if classificacao is not None
            else None
        ),
        "escala_saburra": (diagnostico.escala_saburra if tem_resultado else None),
        "confianca_ia": (diagnostico.confianca_ia if tem_resultado else None),
        "imagens": [
            {
                "id": imagem.id,
                "url_arquivo": imagem.url_arquivo,
                "ordem": imagem.ordem,
                "data_captura": imagem.data_captura,
            }
            for imagem in dados.imagens
        ],
        "anamnese": {
            "id": anamnese.id,
            "data_preenchimento": anamnese.data_preenchimento,
            "respostas": _normalizar_respostas(anamnese.respostas),
        },
        "revisao": revisao,
        "tem_profissional_vinculado": dados.tem_profissional_vinculado,
        "conteudos": [
            {
                "id": conteudo.id,
                "conteudo": conteudo.conteudo,
                "titulo": conteudo.titulo,
            }
            for conteudo in dados.conteudos
        ]
        if tem_resultado
        else [],
        "aviso_legal": AVISO_LEGAL,
        "erro": diagnostico.erro if diagnostico.status == "falha" else None,
    }


async def retry_diagnostico(
    db: AsyncSession,
    paciente_id: int,
    diagnostico_id: int,
) -> dict[str, Any]:
    diagnostico = await diagnostico_queries.buscar_por_id(
        db,
        diagnostico_id,
    )

    if diagnostico is None:
        raise DiagnosticoNaoEncontradoError

    if diagnostico.paciente_id != paciente_id:
        raise DiagnosticoAcessoNegadoError

    if diagnostico.status != "falha":
        raise DiagnosticoRetryInvalidoError

    anamnese = await anamnese_queries.buscar_por_id(
        db,
        diagnostico.anamnese_id,
    )

    if anamnese is None:
        raise AnamneseNaoEncontradaError

    imagens = await diagnostico_queries.listar_imagens(
        db,
        diagnostico.id,
    )

    if not imagens:
        raise ImagemInvalidaError("Imagem do diagnóstico não encontrada.")

    diagnostico = await _processar_com_provider(
        db=db,
        diagnostico=diagnostico,
        anamnese=anamnese,
        url_arquivo=imagens[0].url_arquivo,
    )

    return {
        "id": diagnostico.id,
        "status": diagnostico.status,
        "data_diagnostico": diagnostico.data_diagnostico,
        "anamnese_id": diagnostico.anamnese_id,
    }
