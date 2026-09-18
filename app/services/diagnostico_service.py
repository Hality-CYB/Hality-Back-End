import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import anamnese_queries, diagnostico_queries
from app.models.diagnostico import Diagnostico
from app.schemas.diagnostico import (
    ClassificacaoDiagnosticoResumo,
    DiagnosticoListItem,
    DiagnosticoListResponse,
)
from app.services import diagnostico_mock, diagnostico_storage

AVISO_LEGAL = (
    "Este é um pré-diagnóstico de apoio e não substitui a avaliação de um profissional de saúde."
)

STATUS_COM_RESULTADO = {
    "aguardando_revisao",
    "concluido",
}
STATUS_SEM_RESULTADO_LISTAGEM = {
    "falha",
    "processando",
}
ORDENS_LISTAGEM = {
    "data_asc",
    "data_desc",
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


class DiagnosticoFiltroInvalidoError(Exception):
    def __init__(self, motivo: str) -> None:
        self.motivo = motivo
        super().__init__(motivo)


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


def _normalizar_data_parametro(
    valor: str | None,
    nome: str,
    fim_do_dia: bool,
) -> datetime | None:
    if valor is None:
        return None

    valor = valor.strip()

    try:
        if "T" not in valor and len(valor) == 10:
            data = date.fromisoformat(valor)
            horario = time.max if fim_do_dia else time.min
            return datetime.combine(data, horario, tzinfo=UTC)

        data_hora = datetime.fromisoformat(valor.replace("Z", "+00:00"))

    except ValueError as exc:
        raise DiagnosticoFiltroInvalidoError(f"{nome} deve estar em formato ISO valido") from exc

    if data_hora.tzinfo is None:
        return data_hora.replace(tzinfo=UTC)

    return data_hora


def _normalizar_status(status: str | None) -> str | None:
    if status is None:
        return None

    status = status.strip()

    return status or None


def _validar_filtros_listagem(
    data_inicio: str | None,
    data_fim: str | None,
    pagina: int,
    limite: int,
    ordem: str,
) -> tuple[datetime | None, datetime | None, str]:
    if pagina < 1:
        raise DiagnosticoFiltroInvalidoError("pagina deve ser maior ou igual a 1")

    if limite < 1:
        raise DiagnosticoFiltroInvalidoError("limite deve ser maior ou igual a 1")

    if limite > 50:
        raise DiagnosticoFiltroInvalidoError("limite maximo permitido e 50")

    if ordem not in ORDENS_LISTAGEM:
        raise DiagnosticoFiltroInvalidoError("ordem deve ser data_desc ou data_asc")

    data_inicio_normalizada = _normalizar_data_parametro(
        data_inicio,
        "data_inicio",
        fim_do_dia=False,
    )
    data_fim_normalizada = _normalizar_data_parametro(
        data_fim,
        "data_fim",
        fim_do_dia=True,
    )

    if (
        data_inicio_normalizada is not None
        and data_fim_normalizada is not None
        and data_inicio_normalizada > data_fim_normalizada
    ):
        raise DiagnosticoFiltroInvalidoError("data_inicio deve ser menor ou igual a data_fim")

    return data_inicio_normalizada, data_fim_normalizada, ordem


def _para_item_listagem(
    item: diagnostico_queries.DiagnosticoListado,
) -> DiagnosticoListItem:
    diagnostico = item.diagnostico
    tem_resultado = diagnostico.status not in STATUS_SEM_RESULTADO_LISTAGEM
    classificacao = item.classificacao if tem_resultado else None

    return DiagnosticoListItem(
        id=diagnostico.id,
        data_diagnostico=diagnostico.data_diagnostico,
        status=diagnostico.status,
        classificacao=(
            ClassificacaoDiagnosticoResumo(
                codigo=classificacao.codigo,
                nome_exibicao=classificacao.nome_exibicao,
                ordem=classificacao.ordem,
            )
            if classificacao is not None
            else None
        ),
        escala_saburra=(diagnostico.escala_saburra if tem_resultado else None),
    )


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


async def listar_diagnosticos(
    db: AsyncSession,
    paciente_id: int,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    status: str | None = None,
    pagina: int = 1,
    limite: int = 20,
    ordem: str = "data_desc",
) -> DiagnosticoListResponse:
    data_inicio_normalizada, data_fim_normalizada, ordem_normalizada = _validar_filtros_listagem(
        data_inicio=data_inicio,
        data_fim=data_fim,
        pagina=pagina,
        limite=limite,
        ordem=ordem,
    )

    resultado = await diagnostico_queries.listar_por_paciente(
        db=db,
        paciente_id=paciente_id,
        data_inicio=data_inicio_normalizada,
        data_fim=data_fim_normalizada,
        status=_normalizar_status(status),
        pagina=pagina,
        limite=limite,
        ordem=ordem_normalizada,
    )

    return DiagnosticoListResponse(
        itens=[_para_item_listagem(item) for item in resultado.itens],
        pagina=pagina,
        limite=limite,
        total=resultado.total,
        total_paginas=(resultado.total + limite - 1) // limite,
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

    return {
        "id": diagnostico.id,
        "status": diagnostico.status,
        "data_diagnostico": (diagnostico.data_diagnostico),
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

    diagnostico = await diagnostico_mock.processar_se_necessario(
        db,
        diagnostico,
    )

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
        "data_diagnostico": (diagnostico.data_diagnostico),
        "status": diagnostico.status,
        "classificacao": (
            {
                "id": classificacao.id,
                "codigo": classificacao.codigo,
                "nome_exibicao": (classificacao.nome_exibicao),
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
                "url_arquivo": (imagem.url_arquivo),
                "ordem": imagem.ordem,
                "data_captura": (imagem.data_captura),
            }
            for imagem in dados.imagens
        ],
        "anamnese": {
            "id": anamnese.id,
            "data_preenchimento": (anamnese.data_preenchimento),
            "respostas": [
                resposta.model_dump(mode="json") if hasattr(resposta, "model_dump") else resposta
                for resposta in anamnese.respostas
            ],
        },
        "revisao": revisao,
        "tem_profissional_vinculado": (dados.tem_profissional_vinculado),
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
        "erro": (
            getattr(
                diagnostico,
                "erro",
                None,
            )
            if diagnostico.status == "falha"
            else None
        ),
    }
