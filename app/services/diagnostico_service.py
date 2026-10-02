import uuid
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.policies import (
    UsuarioAutenticado,
    assinar_url_imagem,
    pode_acessar_paciente,
    url_imagem_assinada_valida,
)
from app.core.config import get_settings
from app.db import anamnese_queries, auditoria_queries, diagnostico_queries
from app.models.diagnostico import Diagnostico
from app.schemas.admin_diagnostico import (
    AdminDiagnosticoDetalhe,
    AdminDiagnosticoItem,
    AdminDiagnosticoListResponse,
    ClassificacaoAutomatica,
    DatasetInfo,
    RevisaoProfissional,
)
from app.schemas.diagnostico import (
    ClassificacaoDiagnosticoResumo,
    DiagnosticoListItem,
    DiagnosticoListResponse,
)
from app.schemas.profissional_diagnostico import (
    AnamneseDiagnosticoProfissional,
    DiagnosticoProfissionalDetalhe,
    DiagnosticoProfissionalItem,
    DiagnosticoProfissionalListResponse,
    ImagemDiagnosticoProfissional,
    PacienteDiagnosticoResumo,
    ResultadoAutomaticoDiagnostico,
    RevisaoProfissionalListagem,
    RevisaoProfissionalResponse,
    RevisaoProfissionalResumo,
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

STATUS_VALIDOS_ADMIN = STATUS_COM_RESULTADO | STATUS_SEM_RESULTADO_LISTAGEM
STATUS_VALIDOS_PROFISSIONAL = STATUS_VALIDOS_ADMIN

ACAO_ADMIN_DETALHE_ABERTO = "diagnostico.detalhe.aberto"
RECURSO_DIAGNOSTICO = "diagnostico"

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
    """Carrega o diagnóstico já criado para a anamnese, para o cliente
    retomar o acompanhamento em vez de reenviar (retry idempotente).
    """

    def __init__(self, diagnostico: Diagnostico) -> None:
        self.diagnostico = diagnostico
        super().__init__("anamnese já vinculada a outro diagnóstico")


class DiagnosticoNaoEncontradoError(Exception):
    pass


class DiagnosticoAcessoNegadoError(Exception):
    pass


class ImagemNaoEncontradaError(Exception):
    pass


class ImagemSemCredencialError(Exception):
    pass


class DiagnosticoFiltroInvalidoError(Exception):
    def __init__(self, motivo: str) -> None:
        self.motivo = motivo
        super().__init__(motivo)


class ClassificacaoRevisaoInvalidaError(Exception):
    pass


class DiagnosticoNaoRevisavelError(Exception):
    pass


class DiagnosticoRevisaoConflitoError(Exception):
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
            return datetime.combine(
                data,
                horario,
                tzinfo=UTC,
            )

        data_hora = datetime.fromisoformat(valor.replace("Z", "+00:00"))

    except ValueError as exc:
        raise DiagnosticoFiltroInvalidoError(f"{nome} deve estar em formato ISO valido") from exc

    if data_hora.tzinfo is None:
        return data_hora.replace(tzinfo=UTC)

    return data_hora


def _normalizar_status(
    status: str | None,
) -> str | None:
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

    return (
        data_inicio_normalizada,
        data_fim_normalizada,
        ordem,
    )


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
    revisao_detalhada: diagnostico_queries.DiagnosticoRevisaoDetalhada | None = None,
) -> dict[str, Any] | None:
    if diagnostico.status not in STATUS_COM_RESULTADO:
        return None

    if revisao_detalhada is not None:
        classificacao = revisao_detalhada.classificacao

        return {
            "revisado": True,
            "profissional_nome": revisao_detalhada.profissional_nome,
            "data_revisao": revisao_detalhada.revisao.criado_em,
            "observacoes": revisao_detalhada.revisao.observacao,
            "nivel_corrigido": (diagnostico.classificacao_id != classificacao.id),
            "classificacao": {
                "id": classificacao.id,
                "codigo": classificacao.codigo,
                "nome_exibicao": classificacao.nome_exibicao,
                "ordem": classificacao.ordem,
            },
            "version": revisao_detalhada.revisao.versao,
        }

    revisado_legado = (
        diagnostico.status == "concluido"
        and diagnostico.profissional_revisor_id is not None
        and diagnostico.data_revisao is not None
    )

    if not revisado_legado:
        return {
            "revisado": False,
            "profissional_nome": None,
            "data_revisao": None,
            "observacoes": None,
            "nivel_corrigido": False,
            "classificacao": None,
            "version": 0,
        }

    return {
        "revisado": True,
        "profissional_nome": profissional_nome,
        "data_revisao": diagnostico.data_revisao,
        "observacoes": diagnostico.observacoes_revisao,
        "nivel_corrigido": False,
        "classificacao": None,
        "version": 0,
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
    (
        data_inicio_normalizada,
        data_fim_normalizada,
        ordem_normalizada,
    ) = _validar_filtros_listagem(
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
    usuario: UsuarioAutenticado,
    anamnese_id: int,
    imagem: bytes,
    content_type: str,
    parametros_captura: dict[str, Any],
) -> dict[str, Any]:
    anamnese = await anamnese_queries.buscar_por_id(
        db,
        anamnese_id,
    )

    if anamnese is None or not await pode_acessar_paciente(
        db,
        usuario,
        anamnese.paciente_id,
        recurso=f"anamnese:{anamnese_id}",
    ):
        raise AnamneseNaoEncontradaError

    executor_anamnese = anamnese.executor_id or anamnese.paciente_id

    if executor_anamnese != usuario.id:
        raise AnamneseNaoEncontradaError

    paciente_id = anamnese.paciente_id

    existente = await diagnostico_queries.buscar_por_anamnese(
        db,
        anamnese_id,
    )

    if existente is not None:
        raise AnamneseJaUtilizadaError(existente)

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
            executor_id=usuario.id,
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
            raise AnamneseJaUtilizadaError(existente) from exc

        raise

    except Exception:
        await db.rollback()
        await diagnostico_storage.remover(url_arquivo)
        raise

    return {
        "id": diagnostico.id,
        "status": diagnostico.status,
        "data_diagnostico": diagnostico.data_diagnostico,
        "anamnese_id": anamnese_id,
    }


async def obter_caminho_imagem(
    db: AsyncSession,
    usuario: UsuarioAutenticado | None,
    nome_arquivo: str,
    expira_em: int | None = None,
    assinatura: str | None = None,
) -> Path:
    if usuario is not None:
        paciente_id = await diagnostico_queries.buscar_paciente_por_arquivo_imagem(
            db,
            nome_arquivo,
        )

        permitido = paciente_id is not None and await pode_acessar_paciente(
            db,
            usuario,
            paciente_id,
            recurso=f"imagem:{nome_arquivo}",
        )

    elif expira_em is not None and assinatura is not None:
        permitido = url_imagem_assinada_valida(
            nome_arquivo,
            expira_em,
            assinatura,
        )

    else:
        raise ImagemSemCredencialError

    if not permitido:
        raise ImagemNaoEncontradaError

    caminho = diagnostico_storage.resolver_caminho(nome_arquivo)

    if caminho is None:
        raise ImagemNaoEncontradaError

    return caminho


async def obter_diagnostico(
    db: AsyncSession,
    usuario: UsuarioAutenticado,
    diagnostico_id: int,
) -> dict[str, Any]:
    diagnostico = await diagnostico_queries.buscar_por_id(
        db,
        diagnostico_id,
    )

    if diagnostico is None:
        raise DiagnosticoNaoEncontradoError

    # Contrato legado: diagnóstico existente sem acesso -> 403.
    if not await pode_acessar_paciente(
        db,
        usuario,
        diagnostico.paciente_id,
        recurso=f"diagnostico:{diagnostico_id}",
    ):
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

    ultima_revisao = None

    if tem_resultado:
        ultima_revisao = await diagnostico_queries.buscar_ultima_revisao(
            db,
            diagnostico.id,
        )

    revisao = _montar_revisao(
        diagnostico=diagnostico,
        profissional_nome=dados.profissional_nome,
        revisao_detalhada=ultima_revisao,
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
                "url_arquivo": assinar_url_imagem(
                    imagem.url_arquivo,
                ),
                "ordem": imagem.ordem,
                "data_captura": imagem.data_captura,
            }
            for imagem in dados.imagens
        ],
        "anamnese": {
            "id": anamnese.id,
            "data_preenchimento": (anamnese.data_preenchimento),
            "respostas": [
                (resposta.model_dump(mode="json") if hasattr(resposta, "model_dump") else resposta)
                for resposta in anamnese.respostas
            ],
        },
        "revisao": revisao,
        "tem_profissional_vinculado": (dados.tem_profissional_vinculado),
        "conteudos": (
            [
                {
                    "id": conteudo.id,
                    "conteudo": conteudo.conteudo,
                    "titulo": conteudo.titulo,
                }
                for conteudo in dados.conteudos
            ]
            if tem_resultado
            else []
        ),
        "aviso_legal": AVISO_LEGAL,
        "erro": (diagnostico.erro if diagnostico.status == "falha" else None),
    }


def _resumo_classificacao(
    classificacao,
) -> ClassificacaoDiagnosticoResumo | None:
    if classificacao is None:
        return None

    return ClassificacaoDiagnosticoResumo(
        codigo=classificacao.codigo,
        nome_exibicao=classificacao.nome_exibicao,
        ordem=classificacao.ordem,
    )


def _foi_revisado(
    diagnostico: Diagnostico,
) -> bool:
    return diagnostico.profissional_revisor_id is not None and diagnostico.data_revisao is not None


def _para_revisao_profissional(
    detalhe: diagnostico_queries.DiagnosticoRevisaoDetalhada,
) -> RevisaoProfissionalResumo:
    return RevisaoProfissionalResumo(
        id=detalhe.revisao.id,
        version=detalhe.revisao.versao,
        classificacao=ClassificacaoDiagnosticoResumo(
            codigo=detalhe.classificacao.codigo,
            nome_exibicao=detalhe.classificacao.nome_exibicao,
            ordem=detalhe.classificacao.ordem,
        ),
        profissional_id=detalhe.revisao.profissional_id,
        profissional_nome=detalhe.profissional_nome,
        observacao=detalhe.revisao.observacao,
        criado_em=detalhe.revisao.criado_em,
    )


def _para_revisao_profissional_listagem(
    detalhe: diagnostico_queries.DiagnosticoRevisaoDetalhada,
) -> RevisaoProfissionalListagem:
    return RevisaoProfissionalListagem(
        version=detalhe.revisao.versao,
        classificacao=ClassificacaoDiagnosticoResumo(
            codigo=detalhe.classificacao.codigo,
            nome_exibicao=detalhe.classificacao.nome_exibicao,
            ordem=detalhe.classificacao.ordem,
        ),
    )


async def listar_diagnosticos_profissional(
    db: AsyncSession,
    profissional_id: uuid.UUID,
    paciente_id: uuid.UUID | None = None,
    status: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    pagina: int = 1,
    limite: int = 20,
    ordem: str = "data_desc",
) -> DiagnosticoProfissionalListResponse:
    (
        data_inicio_normalizada,
        data_fim_normalizada,
        ordem_normalizada,
    ) = _validar_filtros_listagem(
        data_inicio=data_inicio,
        data_fim=data_fim,
        pagina=pagina,
        limite=limite,
        ordem=ordem,
    )

    status_normalizado = _normalizar_status(status)

    if status_normalizado is not None and status_normalizado not in STATUS_VALIDOS_PROFISSIONAL:
        raise DiagnosticoFiltroInvalidoError(
            "status deve ser um de: " + ", ".join(sorted(STATUS_VALIDOS_PROFISSIONAL))
        )

    resultado = await diagnostico_queries.listar_profissional(
        db=db,
        profissional_id=profissional_id,
        paciente_id=paciente_id,
        data_inicio=data_inicio_normalizada,
        data_fim=data_fim_normalizada,
        status=status_normalizado,
        pagina=pagina,
        limite=limite,
        ordem=ordem_normalizada,
    )

    diagnostico_ids = [item.diagnostico.id for item in resultado.itens]

    ultimas_revisoes = await diagnostico_queries.listar_ultimas_revisoes(
        db,
        diagnostico_ids,
    )

    itens: list[DiagnosticoProfissionalItem] = []

    for item in resultado.itens:
        diagnostico = item.diagnostico

        ultima_revisao = ultimas_revisoes.get(diagnostico.id)

        revisao = (
            _para_revisao_profissional_listagem(ultima_revisao)
            if ultima_revisao is not None
            else None
        )

        itens.append(
            DiagnosticoProfissionalItem(
                id=diagnostico.id,
                paciente=PacienteDiagnosticoResumo(
                    id=diagnostico.paciente_id,
                    nome=item.paciente_nome,
                ),
                data_diagnostico=(diagnostico.data_diagnostico),
                status=diagnostico.status,
                classificacao_automatica=(
                    _resumo_classificacao(item.classificacao)
                    if diagnostico.status in STATUS_COM_RESULTADO
                    else None
                ),
                tem_revisao=(ultima_revisao is not None or _foi_revisado(diagnostico)),
                revisao=revisao,
            )
        )

    return DiagnosticoProfissionalListResponse(
        itens=itens,
        pagina=pagina,
        limite=limite,
        total=resultado.total,
        total_paginas=(resultado.total + limite - 1) // limite,
    )


async def obter_diagnostico_profissional(
    db: AsyncSession,
    profissional: UsuarioAutenticado,
    diagnostico_id: int,
) -> DiagnosticoProfissionalDetalhe:
    """Retorna o detalhe clínico para um profissional vinculado.

    Diferentemente do detalhe geral do paciente, esta consulta é somente
    leitura e nunca dispara o processamento do provider/mock.
    """

    diagnostico = await diagnostico_queries.buscar_por_id(
        db,
        diagnostico_id,
    )

    if diagnostico is None:
        raise DiagnosticoNaoEncontradoError

    permitido = await pode_acessar_paciente(
        db,
        profissional,
        diagnostico.paciente_id,
        recurso=f"diagnostico:{diagnostico_id}",
    )

    # Nas novas rotas profissionais, inexistente e sem acesso retornam
    # o mesmo erro para evitar enumeração de ids.
    if not permitido:
        raise DiagnosticoNaoEncontradoError

    anamnese = await anamnese_queries.buscar_por_id(
        db,
        diagnostico.anamnese_id,
    )

    if anamnese is None:
        raise AnamneseNaoEncontradaError

    paciente_nome = await diagnostico_queries.buscar_nome_usuario(
        db,
        diagnostico.paciente_id,
    )

    if paciente_nome is None:
        raise DiagnosticoNaoEncontradoError

    imagens = await diagnostico_queries.listar_imagens(
        db,
        diagnostico.id,
    )

    classificacao_automatica = None

    if diagnostico.classificacao_id is not None:
        classificacao_automatica = await diagnostico_queries.buscar_classificacao(
            db,
            diagnostico.classificacao_id,
        )

    historico = await diagnostico_queries.listar_revisoes(
        db,
        diagnostico.id,
    )

    revisao_atual = historico[-1] if historico else None

    version = revisao_atual.revisao.versao if revisao_atual is not None else 0

    tem_resultado = diagnostico.status in STATUS_COM_RESULTADO

    return DiagnosticoProfissionalDetalhe(
        id=diagnostico.id,
        data_diagnostico=diagnostico.data_diagnostico,
        status=diagnostico.status,
        paciente=PacienteDiagnosticoResumo(
            id=diagnostico.paciente_id,
            nome=paciente_nome,
        ),
        anamnese=AnamneseDiagnosticoProfissional(
            id=anamnese.id,
            data_preenchimento=(anamnese.data_preenchimento),
            respostas=[
                (
                    resposta.model_dump(mode="json")
                    if hasattr(
                        resposta,
                        "model_dump",
                    )
                    else resposta
                )
                for resposta in anamnese.respostas
            ],
        ),
        imagens=[
            ImagemDiagnosticoProfissional(
                id=imagem.id,
                url_arquivo=assinar_url_imagem(imagem.url_arquivo),
                ordem=imagem.ordem,
                data_captura=imagem.data_captura,
            )
            for imagem in imagens
        ],
        automatico=(
            ResultadoAutomaticoDiagnostico(
                classificacao=(_resumo_classificacao(classificacao_automatica)),
                escala_saburra=(diagnostico.escala_saburra),
                confianca_ia=(diagnostico.confianca_ia),
            )
            if tem_resultado
            else None
        ),
        revisao=(_para_revisao_profissional(revisao_atual) if revisao_atual is not None else None),
        historico_revisoes=[_para_revisao_profissional(revisao) for revisao in historico],
        version=version,
        aviso_legal=AVISO_LEGAL,
        erro=(diagnostico.erro if diagnostico.status == "falha" else None),
    )


async def revisar_diagnostico_profissional(
    db: AsyncSession,
    profissional: UsuarioAutenticado,
    diagnostico_id: int,
    classificacao_codigo: str,
    observacao: str | None,
    version: int,
) -> RevisaoProfissionalResponse:
    diagnostico = await diagnostico_queries.buscar_por_id(
        db,
        diagnostico_id,
    )

    if diagnostico is None:
        raise DiagnosticoNaoEncontradoError

    permitido = await pode_acessar_paciente(
        db,
        profissional,
        diagnostico.paciente_id,
        recurso=(f"diagnostico:{diagnostico_id}:revisao"),
    )

    if not permitido:
        raise DiagnosticoNaoEncontradoError

    if diagnostico.status not in STATUS_COM_RESULTADO:
        raise DiagnosticoNaoRevisavelError

    codigo = classificacao_codigo.strip()

    classificacao = await diagnostico_queries.buscar_classificacao_por_codigo(
        db,
        codigo,
    )

    if classificacao is None:
        raise ClassificacaoRevisaoInvalidaError

    try:
        revisao = await diagnostico_queries.inserir_revisao(
            db=db,
            diagnostico=diagnostico,
            profissional_id=profissional.id,
            classificacao_id=classificacao.id,
            observacao=observacao,
            versao_esperada=version,
        )

    except IntegrityError as exc:
        # Duas transações podem ler a mesma versão simultaneamente.
        # UNIQUE(diagnostico_id, versao) decide qual gravação vence.
        await db.rollback()
        raise DiagnosticoRevisaoConflitoError from exc

    if revisao is None:
        await db.rollback()
        raise DiagnosticoRevisaoConflitoError

    detalhe = await diagnostico_queries.buscar_ultima_revisao(
        db,
        diagnostico.id,
    )

    if detalhe is None:
        # Estado impossível após um INSERT confirmado. Mantemos uma falha
        # explícita em vez de devolver uma resposta inconsistente.
        raise RuntimeError("revisão criada mas não encontrada")

    revisao_response = _para_revisao_profissional(detalhe)

    return RevisaoProfissionalResponse(
        revisao=revisao_response,
        version=revisao_response.version,
    )


async def listar_diagnosticos_admin(
    db: AsyncSession,
    paciente_id: uuid.UUID | None = None,
    classificacao: str | None = None,
    sem_classificacao: bool = False,
    status: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    pagina: int = 1,
    limite: int = 20,
    ordem: str = "data_desc",
) -> AdminDiagnosticoListResponse:
    (
        data_inicio_normalizada,
        data_fim_normalizada,
        ordem_normalizada,
    ) = _validar_filtros_listagem(
        data_inicio=data_inicio,
        data_fim=data_fim,
        pagina=pagina,
        limite=limite,
        ordem=ordem,
    )

    status_normalizado = _normalizar_status(status)

    if status_normalizado is not None and status_normalizado not in STATUS_VALIDOS_ADMIN:
        raise DiagnosticoFiltroInvalidoError(
            "status deve ser um de: " + ", ".join(sorted(STATUS_VALIDOS_ADMIN))
        )

    classificacao_normalizada = (classificacao or "").strip() or None

    if sem_classificacao and classificacao_normalizada is not None:
        raise DiagnosticoFiltroInvalidoError(
            "sem_classificacao e classificacao nao podem ser usados juntos"
        )

    resultado = await diagnostico_queries.listar_admin(
        db=db,
        paciente_id=paciente_id,
        classificacao_codigo=(classificacao_normalizada),
        sem_classificacao=sem_classificacao,
        status=status_normalizado,
        data_inicio=data_inicio_normalizada,
        data_fim=data_fim_normalizada,
        pagina=pagina,
        limite=limite,
        ordem=ordem_normalizada,
    )

    return AdminDiagnosticoListResponse(
        itens=[
            AdminDiagnosticoItem(
                id=item.diagnostico.id,
                paciente_id=(item.diagnostico.paciente_id),
                data_diagnostico=(item.diagnostico.data_diagnostico),
                status=item.diagnostico.status,
                classificacao=(_resumo_classificacao(item.classificacao)),
                tem_revisao=_foi_revisado(item.diagnostico),
            )
            for item in resultado.itens
        ],
        pagina=pagina,
        limite=limite,
        total=resultado.total,
        total_paginas=(resultado.total + limite - 1) // limite,
    )


async def obter_diagnostico_admin(
    db: AsyncSession,
    admin_id: uuid.UUID,
    diagnostico_id: int,
) -> AdminDiagnosticoDetalhe:
    """Detalhe administrativo. Somente leitura + auditoria de abertura.

    Diferente do detalhe do paciente, NÃO chama `diagnostico_mock`: o admin
    nunca dispara processamento nem altera o diagnóstico.
    """

    diagnostico = await diagnostico_queries.buscar_por_id(
        db,
        diagnostico_id,
    )

    if diagnostico is None:
        raise DiagnosticoNaoEncontradoError

    classificacao = None

    if diagnostico.classificacao_id is not None:
        classificacao = await diagnostico_queries.buscar_classificacao(
            db,
            diagnostico.classificacao_id,
        )

    qtd_imagens = await diagnostico_queries.contar_imagens(
        db,
        diagnostico.id,
    )

    detalhe = AdminDiagnosticoDetalhe(
        id=diagnostico.id,
        paciente_id=diagnostico.paciente_id,
        data_diagnostico=(diagnostico.data_diagnostico),
        status=diagnostico.status,
        erro=(diagnostico.erro if diagnostico.status == "falha" else None),
        automatica=ClassificacaoAutomatica(
            classificacao=(_resumo_classificacao(classificacao)),
            escala_saburra=(diagnostico.escala_saburra),
            confianca_ia=(diagnostico.confianca_ia),
        ),
        revisao=(
            RevisaoProfissional(
                profissional_revisor_id=(diagnostico.profissional_revisor_id),
                data_revisao=(diagnostico.data_revisao),
                observacoes=(diagnostico.observacoes_revisao),
            )
            if _foi_revisado(diagnostico)
            else None
        ),
        dataset=DatasetInfo(),
        anamnese_id=diagnostico.anamnese_id,
        qtd_imagens=qtd_imagens,
    )

    await auditoria_queries.registrar_acesso(
        db,
        ator_id=admin_id,
        acao=ACAO_ADMIN_DETALHE_ABERTO,
        recurso_tipo=RECURSO_DIAGNOSTICO,
        recurso_id=diagnostico.id,
    )

    return detalhe
