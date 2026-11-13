import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.policies import (
    UsuarioAutenticado,
    assinar_upload_token,
    assinar_url_imagem,
    pode_acessar_paciente,
    tem_papel,
    url_imagem_assinada_valida,
    validar_upload_token,
)
from app.core.config import get_settings
from app.core.erros_diagnostico import erro_publico
from app.db import anamnese_queries, auditoria_queries, diagnostico_queries
from app.models.anamnese import Anamnese
from app.models.classificacao_diagnostico import ClassificacaoDiagnostico
from app.models.diagnostico import Diagnostico
from app.models.diagnostico_revisao import DiagnosticoRevisao
from app.models.identity_action import EmailOutbox
from app.models.profissional import Profissional
from app.models.user import User
from app.schemas.admin_diagnostico import (
    MOTIVO_DATASET_INDISPONIVEL,
    AdminDiagnosticoDetalhe,
    AdminDiagnosticoItem,
    AdminDiagnosticoListResponse,
    ClassificacaoAutomatica,
    DatasetInfo,
    ImagemInfo,
    PacienteAdminResumo,
    ReclassificacaoInfo,
    RevisaoHistorica,
    RevisaoProfissional,
    RevisaoResumo,
)
from app.schemas.anamnese import ItemRespostaRegistrada
from app.schemas.diagnostico import (
    STATUS_COM_RESULTADO,
    AnamneseDiagnostico,
    ClassificacaoDiagnosticoDetalhe,
    ClassificacaoDiagnosticoResumo,
    ConteudoDiagnostico,
    DiagnosticoCriadoResponse,
    DiagnosticoListItem,
    DiagnosticoListResponse,
    DiagnosticoPacienteDetalhe,
    ImagemDiagnostico,
    OrigemResultado,
    OrigemResultadoInfo,
    RevisaoDiagnosticoPaciente,
    StatusDiagnostico,
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
from app.schemas.usuario import TipoUsuario
from app.services import (
    consentimento_service,
    diagnostico_provider,
    diagnostico_storage,
    rotulo_dataset_service,
)
from app.services.identity_token_service import (
    DIAGNOSTIC_REVIEW,
    DIAGNOSTIC_REVIEW_OVERRIDE,
)

AVISO_LEGAL = (
    "Este é um pré-diagnóstico de apoio e não substitui a avaliação de um profissional de saúde."
)

STATUS_VALIDOS_ADMIN = {status.value for status in StatusDiagnostico}
STATUS_VALIDOS_PROFISSIONAL = STATUS_VALIDOS_ADMIN

ACAO_ADMIN_DETALHE_ABERTO = "diagnostico.detalhe.aberto"
RECURSO_DIAGNOSTICO = "diagnostico"

ORDENS_LISTAGEM = {
    "data_asc",
    "data_desc",
}


def _tem_resultado(
    diagnostico: Diagnostico,
) -> bool:
    return diagnostico.status in STATUS_COM_RESULTADO


def _origem_resultado(
    diagnostico: Diagnostico,
) -> OrigemResultadoInfo | None:
    if not _tem_resultado(diagnostico) or diagnostico.origem_resultado is None:
        return None

    return OrigemResultadoInfo(
        tipo=OrigemResultado(diagnostico.origem_resultado),
        provider=diagnostico.modelo_provider,
        versao=diagnostico.modelo_versao,
    )


def _campos_erro(
    diagnostico: Diagnostico,
) -> dict[str, str | None]:
    erro = erro_publico(diagnostico.status, diagnostico.erro_codigo)

    if erro is None:
        return {"erro": None, "erro_codigo": None}

    return {"erro": erro.mensagem, "erro_codigo": erro.codigo.value}


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
    revisao: diagnostico_queries.DiagnosticoRevisaoDetalhada | None = None,
) -> DiagnosticoListItem:
    diagnostico = item.diagnostico
    tem_resultado = _tem_resultado(diagnostico)
    classificacao = (
        (revisao.classificacao if revisao is not None else item.classificacao)
        if tem_resultado
        else None
    )

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
    if not _tem_resultado(diagnostico):
        return None

    if revisao_detalhada is not None:
        classificacao = revisao_detalhada.classificacao

        return {
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
            "profissional_nome": None,
            "data_revisao": None,
            "observacoes": None,
            "nivel_corrigido": False,
            "classificacao": None,
            "version": 0,
        }

    return {
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

    revisoes = await diagnostico_queries.buscar_ultimas_revisoes(
        db,
        [item.diagnostico.id for item in resultado.itens],
    )

    return DiagnosticoListResponse(
        itens=[
            _para_item_listagem(
                item,
                revisoes.get(item.diagnostico.id),
            )
            for item in resultado.itens
        ],
        pagina=pagina,
        limite=limite,
        total=resultado.total,
        total_paginas=(resultado.total + limite - 1) // limite,
    )


IMAGEM_LEITURA_VALIDADE_SEGUNDOS = 5 * 60


class UploadInvalidoError(Exception):
    def __init__(self, motivo: str) -> None:
        self.motivo = motivo
        super().__init__(motivo)


MOTIVO_UPLOAD_INVALIDO = "Envio da imagem inválido ou expirado. Envie a foto de novo."
MOTIVO_UPLOAD_AUSENTE = "A imagem não foi enviada. Envie a foto de novo."


async def _anamnese_para_envio(
    db: AsyncSession,
    usuario: UsuarioAutenticado,
    anamnese_id: int,
) -> Anamnese:
    """Checagens comuns de todo envio de foto; devolve a anamnese travada."""
    # Lock até o commit: um reenvio concorrente espera e recebe 409.
    anamnese = await anamnese_queries.buscar_por_id(
        db,
        anamnese_id,
        bloquear=True,
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

    existente = await diagnostico_queries.buscar_por_anamnese(
        db,
        anamnese_id,
    )

    if existente is not None:
        raise AnamneseJaUtilizadaError(existente)

    # O titular é o dono da anamnese, mesmo quando quem envia é o profissional.
    await consentimento_service.exigir_tratamento_vigente_se_decidido(db, anamnese.paciente_id)

    return anamnese


async def preparar_upload(
    db: AsyncSession,
    usuario: UsuarioAutenticado,
    anamnese_id: int,
    content_type: str,
) -> tuple[diagnostico_storage.AlvoDeUpload, str]:
    """Alvo para o navegador enviar a foto direto ao storage, e o token de confirmação."""
    await _anamnese_para_envio(db, usuario, anamnese_id)
    # O rollback expira o usuário da sessão: o id é lido antes dele.
    usuario_id = usuario.id
    # Só leitura: solta o lock da anamnese (nos erros, quem fecha a sessão solta).
    await db.rollback()

    if not diagnostico_storage.formato_aceito(content_type):
        raise ImagemInvalidaError("Formato de imagem inválido. Envie JPEG, PNG ou WEBP.")

    chave, alvo = await diagnostico_storage.preparar_upload(content_type)
    token = assinar_upload_token(
        chave=chave,
        usuario_id=usuario_id,
        anamnese_id=anamnese_id,
        content_type=content_type,
    )

    return alvo, token


async def _inserir_diagnostico(
    db: AsyncSession,
    usuario: UsuarioAutenticado,
    paciente_id: uuid.UUID,
    anamnese_id: int,
    url_arquivo: str,
    imagem: bytes,
    content_type: str,
    parametros_captura: dict[str, Any],
) -> DiagnosticoCriadoResponse:
    sha256 = await diagnostico_storage.calcular_sha256(imagem)

    try:
        diagnostico = await diagnostico_queries.inserir(
            db=db,
            paciente_id=paciente_id,
            executor_id=usuario.id,
            anamnese_id=anamnese_id,
            arquivo=diagnostico_queries.ArquivoImagem(
                url_arquivo=url_arquivo,
                sha256=sha256,
                content_type=content_type,
                tamanho_bytes=len(imagem),
            ),
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

    return DiagnosticoCriadoResponse(
        id=diagnostico.id,
        status=diagnostico.status,
        data_diagnostico=diagnostico.data_diagnostico,
        anamnese_id=anamnese_id,
    )


async def criar_diagnostico(
    db: AsyncSession,
    usuario: UsuarioAutenticado,
    anamnese_id: int,
    imagem: bytes,
    content_type: str,
    parametros_captura: dict[str, Any],
) -> DiagnosticoCriadoResponse:
    anamnese = await _anamnese_para_envio(db, usuario, anamnese_id)

    _validar_imagem(
        imagem,
        content_type,
    )

    url_arquivo = await diagnostico_storage.salvar(
        imagem,
        content_type,
        get_settings().api_v1_prefix,
    )

    return await _inserir_diagnostico(
        db,
        usuario,
        anamnese.paciente_id,
        anamnese_id,
        url_arquivo,
        imagem,
        content_type,
        parametros_captura,
    )


async def confirmar_upload(
    db: AsyncSession,
    usuario: UsuarioAutenticado,
    anamnese_id: int,
    upload_token: str,
    parametros_captura: dict[str, Any],
) -> DiagnosticoCriadoResponse:
    """Confirma a foto enviada direto ao storage e cria o diagnóstico."""
    token = validar_upload_token(upload_token, usuario_id=usuario.id, anamnese_id=anamnese_id)

    if token is None:
        raise UploadInvalidoError(MOTIVO_UPLOAD_INVALIDO)

    try:
        anamnese = await _anamnese_para_envio(db, usuario, anamnese_id)
    except AnamneseJaUtilizadaError:
        await diagnostico_storage.remover_upload(token.chave)
        raise

    try:
        url_arquivo, imagem = await diagnostico_storage.consolidar_upload(
            token.chave, get_settings().api_v1_prefix
        )
    except FileNotFoundError as exc:
        raise UploadInvalidoError(MOTIVO_UPLOAD_AUSENTE) from exc

    try:
        _validar_imagem(imagem, token.content_type)
    except (ImagemInvalidaError, ArquivoMuitoGrandeError):
        await diagnostico_storage.remover(url_arquivo)
        raise

    return await _inserir_diagnostico(
        db,
        usuario,
        anamnese.paciente_id,
        anamnese_id,
        url_arquivo,
        imagem,
        token.content_type,
        parametros_captura,
    )


async def obter_leitura_imagem(
    db: AsyncSession,
    usuario: UsuarioAutenticado | None,
    nome_arquivo: str,
    expira_em: int | None = None,
    assinatura: str | None = None,
) -> diagnostico_storage.ArquivoLocal | diagnostico_storage.UrlAssinada:
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

    leitura = await diagnostico_storage.leitura(nome_arquivo, IMAGEM_LEITURA_VALIDADE_SEGUNDOS)

    if leitura is None:
        raise ImagemNaoEncontradaError

    return leitura


async def obter_diagnostico(
    db: AsyncSession,
    usuario: UsuarioAutenticado,
    diagnostico_id: int,
) -> DiagnosticoPacienteDetalhe:
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

    diagnostico = await diagnostico_provider.processar_se_necessario(
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

    tem_resultado = _tem_resultado(diagnostico)

    ultima_revisao = None

    if tem_resultado:
        ultima_revisao = await diagnostico_queries.buscar_ultima_revisao(
            db,
            diagnostico.id,
        )

    classificacao = None
    conteudos = []

    if tem_resultado:
        classificacao = (
            ultima_revisao.classificacao if ultima_revisao is not None else dados.classificacao
        )
        conteudos = dados.conteudos

        revisao_mudou_classificacao = ultima_revisao is not None and (
            dados.classificacao is None or dados.classificacao.id != ultima_revisao.classificacao.id
        )

        if revisao_mudou_classificacao:
            conteudos = await diagnostico_queries.listar_conteudos_por_classificacao(
                db,
                ultima_revisao.classificacao.id,
            )

    revisao = _montar_revisao(
        diagnostico=diagnostico,
        profissional_nome=dados.profissional_nome,
        revisao_detalhada=ultima_revisao,
    )

    return DiagnosticoPacienteDetalhe(
        id=diagnostico.id,
        data_diagnostico=diagnostico.data_diagnostico,
        status=diagnostico.status,
        classificacao=(
            ClassificacaoDiagnosticoDetalhe(
                id=classificacao.id,
                codigo=classificacao.codigo,
                nome_exibicao=classificacao.nome_exibicao,
                ordem=classificacao.ordem,
            )
            if classificacao is not None
            else None
        ),
        escala_saburra=(diagnostico.escala_saburra if tem_resultado else None),
        confianca_ia=(diagnostico.confianca_ia if tem_resultado else None),
        imagens=[
            ImagemDiagnostico(
                id=imagem.id,
                url_arquivo=assinar_url_imagem(imagem.url_arquivo),
                ordem=imagem.ordem,
                data_captura=imagem.data_captura,
            )
            for imagem in dados.imagens
        ],
        anamnese=AnamneseDiagnostico(
            id=anamnese.id,
            paciente_id=anamnese.paciente_id,
            data_preenchimento=anamnese.data_preenchimento,
            versao_questionario=anamnese.id_versao_questionario,
            respostas=[
                ItemRespostaRegistrada.model_validate(resposta).model_dump(
                    mode="json",
                    by_alias=True,
                )
                for resposta in anamnese.respostas
            ],
        ),
        revisao=(RevisaoDiagnosticoPaciente(**revisao) if revisao is not None else None),
        tem_profissional_vinculado=dados.tem_profissional_vinculado,
        conteudos=[
            ConteudoDiagnostico(
                id=conteudo.id,
                conteudo=conteudo.conteudo,
                titulo=conteudo.titulo,
            )
            for conteudo in conteudos
        ],
        aviso_legal=AVISO_LEGAL,
        **_campos_erro(diagnostico),
    )


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


def _valores_revisao_admin(
    diagnostico: Diagnostico,
    ultima_revisao: diagnostico_queries.DiagnosticoRevisaoDetalhada | None,
) -> dict[str, Any]:
    if ultima_revisao is not None:
        return {
            "status": "concluida",
            "profissional_revisor_id": ultima_revisao.revisao.profissional_id,
            "profissional_revisor_nome": ultima_revisao.profissional_nome,
            "data_revisao": ultima_revisao.revisao.criado_em,
            "classificacao": _resumo_classificacao(ultima_revisao.classificacao),
            "observacoes": ultima_revisao.revisao.observacao,
        }

    return {
        "status": "concluida" if _foi_revisado(diagnostico) else "pendente",
        "profissional_revisor_id": diagnostico.profissional_revisor_id,
        "profissional_revisor_nome": None,
        "data_revisao": diagnostico.data_revisao,
        "classificacao": None,
        "observacoes": diagnostico.observacoes_revisao,
    }


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
    diagnostico: Diagnostico,
    detalhe: diagnostico_queries.DiagnosticoRevisaoDetalhada,
) -> RevisaoProfissionalListagem:
    return RevisaoProfissionalListagem(
        version=detalhe.revisao.versao,
        profissional_nome=detalhe.profissional_nome,
        data_revisao=detalhe.revisao.criado_em,
        observacoes=detalhe.revisao.observacao,
        nivel_corrigido=(diagnostico.classificacao_id != detalhe.classificacao.id),
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
            _para_revisao_profissional_listagem(
                diagnostico,
                ultima_revisao,
            )
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
                    if _tem_resultado(diagnostico)
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
                classificacao=_resumo_classificacao(classificacao_automatica),
                escala_saburra=diagnostico.escala_saburra,
                confianca_ia=diagnostico.confianca_ia,
                origem=_origem_resultado(diagnostico),
            )
            if _tem_resultado(diagnostico)
            else None
        ),
        revisao=(_para_revisao_profissional(revisao_atual) if revisao_atual is not None else None),
        historico_revisoes=[_para_revisao_profissional(revisao) for revisao in historico],
        version=version,
        aviso_legal=AVISO_LEGAL,
        **_campos_erro(diagnostico),
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

    if not _tem_resultado(diagnostico):
        raise DiagnosticoNaoRevisavelError

    codigo = classificacao_codigo.strip()

    classificacao = await diagnostico_queries.buscar_classificacao_por_codigo(
        db,
        codigo,
    )

    if classificacao is None:
        raise ClassificacaoRevisaoInvalidaError

    await _gravar_revisao(
        db,
        diagnostico=diagnostico,
        autor_id=profissional.id,
        classificacao_id=classificacao.id,
        observacao=observacao,
        version=version,
    )
    await db.commit()

    return await _resposta_da_revisao(db, diagnostico.id)


async def _gravar_revisao(
    db: AsyncSession,
    *,
    diagnostico: Diagnostico,
    autor_id: uuid.UUID,
    classificacao_id: int,
    observacao: str | None,
    version: int,
) -> DiagnosticoRevisao:
    """Grava a revisão e enfileira o aviso ao paciente; o commit é do chamador."""
    try:
        revisao = await diagnostico_queries.inserir_revisao(
            db=db,
            diagnostico=diagnostico,
            profissional_id=autor_id,
            classificacao_id=classificacao_id,
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

    paciente = await db.get(User, diagnostico.paciente_id)
    if paciente is None:
        await db.rollback()
        raise RuntimeError("paciente da revisão não encontrado")
    db.add(
        EmailOutbox(
            review_id=revisao.id,
            recipient_email=paciente.email,
            purpose=DIAGNOSTIC_REVIEW,
            status="queued",
            correlation_id=uuid.uuid4().hex,
        )
    )
    return revisao


async def _resposta_da_revisao(
    db: AsyncSession,
    diagnostico_id: int,
) -> RevisaoProfissionalResponse:
    detalhe = await diagnostico_queries.buscar_ultima_revisao(
        db,
        diagnostico_id,
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


async def _profissional_que_revisou(
    db: AsyncSession,
    diagnostico: Diagnostico,
    ultima_revisao: diagnostico_queries.DiagnosticoRevisaoDetalhada | None,
) -> Profissional | None:
    """Perfil do último revisor; revisão feita pelo admin não tem perfil profissional."""
    autor_id = (
        ultima_revisao.revisao.profissional_id
        if ultima_revisao is not None
        else diagnostico.profissional_revisor_id
    )
    return await db.get(Profissional, autor_id) if autor_id is not None else None


async def reclassificar_diagnostico_admin(
    db: AsyncSession,
    admin: User,
    diagnostico_id: int,
    classificacao_codigo: str,
    observacao: str | None,
    version: int,
) -> RevisaoProfissionalResponse:
    """Reclassifica para o paciente, com o mesmo efeito da revisão do profissional.

    Não depende de vínculo. Se a mudança passa por cima da classificação de um
    profissional, ele é avisado por e-mail na mesma transação.
    """
    diagnostico = await diagnostico_queries.buscar_por_id(db, diagnostico_id)

    if diagnostico is None:
        raise DiagnosticoNaoEncontradoError

    if not _tem_resultado(diagnostico):
        raise DiagnosticoNaoRevisavelError

    classificacao = await diagnostico_queries.buscar_classificacao_por_codigo(
        db,
        classificacao_codigo.strip(),
    )

    if classificacao is None:
        raise ClassificacaoRevisaoInvalidaError

    # A checagem de `version` no insert garante que esta ainda é a última revisão.
    anterior = await diagnostico_queries.buscar_ultima_revisao(db, diagnostico.id)
    perfil = await _profissional_que_revisou(db, diagnostico, anterior)
    classificacao_anterior_id = (
        anterior.revisao.classificacao_id if anterior is not None else diagnostico.classificacao_id
    )

    revisao = await _gravar_revisao(
        db,
        diagnostico=diagnostico,
        autor_id=admin.id,
        classificacao_id=classificacao.id,
        observacao=observacao,
        version=version,
    )

    avisou_profissional = False
    if perfil is not None and classificacao_anterior_id != classificacao.id:
        profissional = await db.get(User, perfil.usuario_id)
        if profissional is not None:
            db.add(
                EmailOutbox(
                    review_id=revisao.id,
                    recipient_email=profissional.email,
                    purpose=DIAGNOSTIC_REVIEW_OVERRIDE,
                    status="queued",
                    correlation_id=uuid.uuid4().hex,
                )
            )
            avisou_profissional = True

    await auditoria_queries.registrar_mutacao(
        db,
        admin,
        "diagnostico.revisao.admin",
        "diagnostico",
        diagnostico.id,
        metadata={
            "version": revisao.versao,
            "classificacao": classificacao.codigo,
            "avisou_profissional": avisou_profissional,
        },
    )
    await db.commit()

    return await _resposta_da_revisao(db, diagnostico.id)


def _classificacao_automatica_admin(
    diagnostico: Diagnostico,
    classificacao: ClassificacaoDiagnostico | None,
) -> ClassificacaoAutomatica:
    if not _tem_resultado(diagnostico):
        return ClassificacaoAutomatica(
            classificacao=None,
            escala_saburra=None,
            confianca_ia=None,
            origem=None,
        )

    return ClassificacaoAutomatica(
        classificacao=_resumo_classificacao(classificacao),
        escala_saburra=diagnostico.escala_saburra,
        confianca_ia=diagnostico.confianca_ia,
        origem=_origem_resultado(diagnostico),
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
    exportacao_habilitada: bool = False,
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
    diagnostico_ids = [item.diagnostico.id for item in resultado.itens]
    quantidades_imagens = await diagnostico_queries.contar_imagens_por_diagnosticos(
        db,
        diagnostico_ids,
    )
    ultimas_revisoes = await diagnostico_queries.buscar_ultimas_revisoes(
        db,
        diagnostico_ids,
    )
    elegibilidade = await rotulo_dataset_service.elegibilidade_em_lote(
        db,
        [item.diagnostico for item in resultado.itens],
        quantidades_imagens,
        {
            diagnostico_id: revisao.revisao.profissional_id
            for diagnostico_id, revisao in ultimas_revisoes.items()
        },
    )

    return AdminDiagnosticoListResponse(
        itens=[
            AdminDiagnosticoItem(
                id=item.diagnostico.id,
                paciente_id=(item.diagnostico.paciente_id),
                paciente=PacienteAdminResumo(
                    id=item.diagnostico.paciente_id,
                    nome=item.paciente_nome or "",
                ),
                data=(item.diagnostico.data_diagnostico),
                status=item.diagnostico.status,
                automatica=_classificacao_automatica_admin(
                    item.diagnostico,
                    item.classificacao,
                ),
                revisao=RevisaoResumo(
                    **_valores_revisao_admin(
                        item.diagnostico,
                        ultimas_revisoes.get(item.diagnostico.id),
                    )
                ),
                qtd_imagens=quantidades_imagens.get(item.diagnostico.id, 0),
                dataset=elegibilidade[item.diagnostico.id],
            )
            for item in resultado.itens
        ],
        exportacao_habilitada=exportacao_habilitada,
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

    Traz a foto e a anamnese, como o detalhe do profissional: o admin usa as
    duas para rotular e reclassificar (decisão do time em 2026-11-13). Diferente
    do detalhe do paciente, NÃO chama `diagnostico_mock`: o admin nunca dispara
    processamento nem altera o diagnóstico.
    """

    diagnostico = await diagnostico_queries.buscar_por_id(
        db,
        diagnostico_id,
    )

    if diagnostico is None:
        raise DiagnosticoNaoEncontradoError

    paciente = await db.get(User, diagnostico.paciente_id)
    if paciente is None:
        raise DiagnosticoNaoEncontradoError

    classificacao = None

    if diagnostico.classificacao_id is not None:
        classificacao = await diagnostico_queries.buscar_classificacao(
            db,
            diagnostico.classificacao_id,
        )

    imagens = await diagnostico_queries.listar_imagens(db, diagnostico.id)
    qtd_imagens = len(imagens)
    anamnese = (
        await anamnese_queries.buscar_por_id(db, diagnostico.anamnese_id)
        if diagnostico.anamnese_id is not None
        else None
    )
    historico = await diagnostico_queries.listar_revisoes(db, diagnostico.id)
    ultima_revisao = historico[-1] if historico else None

    autor_revisao = (
        await db.get(User, ultima_revisao.revisao.profissional_id) if ultima_revisao else None
    )
    rotulo_dataset = await rotulo_dataset_service.obter_info(
        db,
        diagnostico,
        ultima_revisao is not None,
        fonte_revisao="hality"
        if autor_revisao and tem_papel(autor_revisao, TipoUsuario.ADMIN)
        else "profissional",
    )

    revisao = RevisaoProfissional(**_valores_revisao_admin(diagnostico, ultima_revisao))
    perfil_do_revisor = await _profissional_que_revisou(db, diagnostico, ultima_revisao)

    detalhe = AdminDiagnosticoDetalhe(
        id=diagnostico.id,
        paciente_id=diagnostico.paciente_id,
        paciente=PacienteAdminResumo(id=paciente.id, nome=paciente.name),
        data=diagnostico.data_diagnostico,
        status=diagnostico.status,
        **_campos_erro(diagnostico),
        automatica=_classificacao_automatica_admin(diagnostico, classificacao),
        revisao=revisao,
        historico_revisoes=[
            RevisaoHistorica(
                profissional_revisor_id=registro.revisao.profissional_id,
                profissional_revisor_nome=registro.profissional_nome,
                data_revisao=registro.revisao.criado_em,
                classificacao=_resumo_classificacao(registro.classificacao),
                observacoes=registro.revisao.observacao,
            )
            for registro in historico
        ],
        dataset=DatasetInfo(
            disponivel=False,
            motivo=MOTIVO_DATASET_INDISPONIVEL,
        ),
        rotulo_dataset=rotulo_dataset,
        reclassificacao=ReclassificacaoInfo(
            version=ultima_revisao.revisao.versao if ultima_revisao is not None else 0,
            revisada_por_profissional=perfil_do_revisor is not None,
        ),
        anamnese_id=diagnostico.anamnese_id,
        qtd_imagens=qtd_imagens,
        imagem=ImagemInfo(disponivel=qtd_imagens > 0, motivo=None),
        imagens=[
            ImagemDiagnostico(
                id=imagem.id,
                url_arquivo=assinar_url_imagem(imagem.url_arquivo),
                ordem=imagem.ordem,
                data_captura=imagem.data_captura,
            )
            for imagem in imagens
        ],
        anamnese=(
            AnamneseDiagnostico(
                id=anamnese.id,
                paciente_id=anamnese.paciente_id,
                data_preenchimento=anamnese.data_preenchimento,
                versao_questionario=anamnese.id_versao_questionario,
                respostas=[
                    ItemRespostaRegistrada.model_validate(resposta).model_dump(
                        mode="json",
                        by_alias=True,
                    )
                    for resposta in anamnese.respostas
                ],
            )
            if anamnese is not None
            else None
        ),
    )

    await auditoria_queries.registrar_acesso(
        db,
        actor=admin_id,
        action=ACAO_ADMIN_DETALHE_ABERTO,
        resource=RECURSO_DIAGNOSTICO,
        resource_id=diagnostico.id,
    )
    await db.commit()

    return detalhe
