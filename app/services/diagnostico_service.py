from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import diagnostico_queries
from app.db.anamnese_store import (
    AnamneseRepository,
)
from app.models.diagnostico import Diagnostico
from app.services import (
    diagnostico_mock,
    diagnostico_storage,
)

AVISO_LEGAL = (
    "Este é um pré-diagnóstico de apoio "
    "e não substitui a avaliação de um "
    "profissional de saúde."
)

STATUS_COM_RESULTADO = {
    "aguardando_revisao",
    "concluido",
}


class ImagemInvalidaError(Exception):
    def __init__(
        self,
        motivo: str,
    ) -> None:
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


def _validar_imagem(
    imagem: bytes,
    content_type: str,
) -> None:
    if not imagem:
        raise ImagemInvalidaError(
            "A imagem enviada está vazia."
        )

    if (
        len(imagem)
        > diagnostico_storage.MAX_IMAGE_BYTES
    ):
        raise ArquivoMuitoGrandeError

    if content_type not in {
        "image/jpeg",
        "image/png",
        "image/webp",
    }:
        raise ImagemInvalidaError(
            "Formato de imagem inválido. "
            "Envie JPEG, PNG ou WEBP."
        )


def _montar_revisao(
    diagnostico: Diagnostico,
    profissional_nome: str | None,
) -> dict[str, Any] | None:
    if (
        diagnostico.status
        not in STATUS_COM_RESULTADO
    ):
        return None

    revisado = (
        diagnostico.status == "concluido"
        and diagnostico.profissional_revisor_id
        is not None
        and diagnostico.data_revisao
        is not None
    )

    return {
        "revisado": revisado,
        "profissional_nome": (
            profissional_nome
            if revisado
            else None
        ),
        "data_revisao": (
            diagnostico.data_revisao
            if revisado
            else None
        ),
        "observacoes": (
            diagnostico.observacoes_revisao
            if revisado
            else None
        ),
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


async def criar_diagnostico(
    db: AsyncSession,
    repo_anamnese: AnamneseRepository,
    paciente_id: int,
    anamnese_id: int,
    imagem: bytes,
    content_type: str,
    parametros_captura: dict[str, Any],
) -> dict[str, Any]:
    anamnese = repo_anamnese.obter_por_id(
        anamnese_id
    )

    if (
        anamnese is None
        or anamnese.paciente_id
        != paciente_id
    ):
        raise AnamneseNaoEncontradaError

    existente = (
        await diagnostico_queries
        .buscar_por_anamnese(
            db,
            anamnese_id,
        )
    )

    if existente is not None:
        raise AnamneseJaUtilizadaError

    _validar_imagem(
        imagem,
        content_type,
    )

    url_arquivo = (
        await diagnostico_storage.salvar(
            imagem,
            content_type,
            get_settings().api_v1_prefix,
        )
    )

    try:
        diagnostico = (
            await diagnostico_queries.inserir(
                db=db,
                paciente_id=paciente_id,
                anamnese_id=anamnese_id,
                url_arquivo=url_arquivo,
                parametros_captura=(
                    parametros_captura
                ),
            )
        )

    except IntegrityError as exc:
        await db.rollback()

        await diagnostico_storage.remover(
            url_arquivo
        )

        existente = (
            await diagnostico_queries
            .buscar_por_anamnese(
                db,
                anamnese_id,
            )
        )

        if existente is not None:
            raise (
                AnamneseJaUtilizadaError
            ) from exc

        raise

    except Exception:
        await db.rollback()

        await diagnostico_storage.remover(
            url_arquivo
        )

        raise

    return {
        "id": diagnostico.id,
        "status": diagnostico.status,
        "data_diagnostico": (
            diagnostico.data_diagnostico
        ),
        "anamnese_id": anamnese_id,
    }


async def obter_diagnostico(
    db: AsyncSession,
    repo_anamnese: AnamneseRepository,
    paciente_id: int,
    diagnostico_id: int,
) -> dict[str, Any]:
    diagnostico = (
        await diagnostico_queries
        .buscar_por_id(
            db,
            diagnostico_id,
        )
    )

    if diagnostico is None:
        raise DiagnosticoNaoEncontradoError

    if (
        diagnostico.paciente_id
        != paciente_id
    ):
        raise DiagnosticoAcessoNegadoError

    diagnostico = (
        await diagnostico_mock
        .processar_se_necessario(
            db,
            diagnostico,
        )
    )

    if diagnostico.anamnese_id is None:
        raise AnamneseNaoEncontradaError

    anamnese = repo_anamnese.obter_por_id(
        diagnostico.anamnese_id
    )

    if anamnese is None:
        raise AnamneseNaoEncontradaError

    dados = (
        await diagnostico_queries
        .buscar_dados_detalhe(
            db,
            diagnostico,
        )
    )

    tem_resultado = (
        diagnostico.status
        in STATUS_COM_RESULTADO
    )

    classificacao = (
        dados.classificacao
        if tem_resultado
        else None
    )

    revisao = _montar_revisao(
        diagnostico,
        dados.profissional_nome,
    )

    return {
        "id": diagnostico.id,
        "data_diagnostico": (
            diagnostico.data_diagnostico
        ),
        "status": diagnostico.status,
        "classificacao": (
            {
                "id": classificacao.id,
                "codigo": classificacao.codigo,
                "nome_exibicao": (
                    classificacao.nome_exibicao
                ),
                "ordem": classificacao.ordem,
            }
            if classificacao is not None
            else None
        ),
        "escala_saburra": (
            diagnostico.escala_saburra
            if tem_resultado
            else None
        ),
        "confianca_ia": (
            diagnostico.confianca_ia
            if tem_resultado
            else None
        ),
        "imagens": [
            {
                "id": imagem.id,
                "url_arquivo": (
                    imagem.url_arquivo
                ),
                "ordem": imagem.ordem,
                "data_captura": (
                    imagem.data_captura
                ),
            }
            for imagem in dados.imagens
        ],
        "anamnese": {
            "id": anamnese.id,
            "data_preenchimento": (
                anamnese.data_preenchimento
            ),
            "respostas": [
                resposta.model_dump(
                    mode="json"
                )
                for resposta
                in anamnese.respostas
            ],
        },
        "revisao": revisao,
        "tem_profissional_vinculado": (
            dados.tem_profissional_vinculado
        ),
        "conteudos": [
            {
                "id": conteudo.id,
                "tipo": conteudo.tipo,
                "titulo": conteudo.titulo,
                "dados": conteudo.dados,
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