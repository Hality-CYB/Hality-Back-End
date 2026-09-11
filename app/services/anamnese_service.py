from collections import Counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import anamnese_queries
from app.models.anamnese import Anamnese
from app.schemas.anamnese import (
    AnamneseCreate,
    AnamneseCreated,
    AnamneseDetail,
    Pergunta,
    Questionario,
    RespostaItem,
    TipoPergunta,
)
from app.services.anamnese_questionnaire import QUESTIONARIO_VIGENTE


class AnamneseValidationError(Exception):
    """Levantada quando o payload tem pergunta obrigatória ausente ou valor
    fora do tipo/escala esperado (issue #18 pede 400 nesses casos)."""

    def __init__(self, erros: list[str]) -> None:
        self.erros = erros
        super().__init__("; ".join(erros))


class AnamneseNaoEncontradaError(Exception):
    pass


def _validar_valor(pergunta: Pergunta, valor: bool | str | int) -> str | None:
    match pergunta.tipo:
        case TipoPergunta.BOOLEAN:
            if not isinstance(valor, bool):
                return f"valor fora do tipo esperado para '{pergunta.id}' (esperado boolean)"
        case TipoPergunta.SINGLE_CHOICE:
            if not pergunta.opcoes:
                return f"pergunta '{pergunta.id}' não tem opções configuradas"
            if not isinstance(valor, str) or valor not in pergunta.opcoes:
                return f"valor fora das opções válidas para '{pergunta.id}'"
        case TipoPergunta.TEXT:
            if not isinstance(valor, str) or not valor.strip():
                return f"valor fora do tipo esperado para '{pergunta.id}' (esperado texto)"
        case TipoPergunta.SCALE:
            minimo = pergunta.escala_min if pergunta.escala_min is not None else 1
            maximo = pergunta.escala_max if pergunta.escala_max is not None else 5
            fora_do_tipo = isinstance(valor, bool) or not isinstance(valor, int)
            if fora_do_tipo or not (minimo <= valor <= maximo):
                return f"valor fora da escala {minimo}-{maximo} para '{pergunta.id}'"
    return None


def validar_respostas(questionario: Questionario, payload: AnamneseCreate) -> None:
    erros: list[str] = []

    if payload.versao_questionario != questionario.versao:
        erros.append(
            f"versão do questionário desatualizada: esperado '{questionario.versao}', "
            f"recebido '{payload.versao_questionario}'"
        )

    ids_recebidos = [r.pergunta_id for r in payload.respostas]
    for pergunta_id, quantidade in Counter(ids_recebidos).items():
        if quantidade > 1:
            erros.append(f"resposta duplicada para pergunta '{pergunta_id}'")

    respostas_por_pergunta = {r.pergunta_id: r for r in payload.respostas}
    perguntas_por_id = {p.id: p for p in questionario.perguntas}

    for pergunta in questionario.perguntas:
        resposta = respostas_por_pergunta.get(pergunta.id)
        valor_ausente = resposta is None or resposta.valor is None or resposta.valor == ""
        if pergunta.obrigatoria and valor_ausente:
            erros.append(f"pergunta obrigatória ausente: '{pergunta.id}'")
            continue
        if resposta is None or valor_ausente:
            continue
        if resposta.tipo != pergunta.tipo:
            erros.append(f"tipo incompatível para pergunta '{pergunta.id}'")
            continue
        erro = _validar_valor(pergunta, resposta.valor)
        if erro:
            erros.append(erro)

    for resposta in payload.respostas:
        if resposta.pergunta_id not in perguntas_por_id:
            erros.append(f"pergunta desconhecida: '{resposta.pergunta_id}'")

    if erros:
        raise AnamneseValidationError(erros)


def _respostas_para_persistir(questionario: Questionario, payload: AnamneseCreate) -> list[dict]:
    """Usa enunciado/tipo do catálogo ativo, não os que vieram do front — evita
    persistir texto divergente caso o questionário mude (comentário do PR)."""
    perguntas_por_id = {p.id: p for p in questionario.perguntas}
    return [
        {
            "pergunta_id": r.pergunta_id,
            "enunciado": perguntas_por_id[r.pergunta_id].enunciado,
            "tipo": perguntas_por_id[r.pergunta_id].tipo.value,
            "valor": r.valor,
        }
        for r in payload.respostas
    ]


def _para_detalhe(anamnese: Anamnese) -> AnamneseDetail:
    return AnamneseDetail(
        id=anamnese.id,
        paciente_id=anamnese.paciente_id,
        data_preenchimento=anamnese.data_preenchimento,
        respostas=[RespostaItem(**r) for r in anamnese.respostas],
    )


async def criar_anamnese(
    db: AsyncSession, paciente_id: int, payload: AnamneseCreate
) -> AnamneseCreated:
    validar_respostas(QUESTIONARIO_VIGENTE, payload)
    anamnese = await anamnese_queries.inserir(
        db, paciente_id, _respostas_para_persistir(QUESTIONARIO_VIGENTE, payload)
    )
    return AnamneseCreated(
        id=anamnese.id,
        paciente_id=anamnese.paciente_id,
        data_preenchimento=anamnese.data_preenchimento,
    )


async def listar_anamneses(db: AsyncSession, paciente_id: int) -> list[AnamneseDetail]:
    anamneses = await anamnese_queries.listar_por_paciente(db, paciente_id)
    return [_para_detalhe(a) for a in anamneses]


async def obter_anamnese(db: AsyncSession, paciente_id: int, anamnese_id: int) -> AnamneseDetail:
    anamnese = await anamnese_queries.buscar_por_id(db, anamnese_id)
    if anamnese is None or anamnese.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError
    return _para_detalhe(anamnese)


async def atualizar_anamnese(
    db: AsyncSession, paciente_id: int, anamnese_id: int, payload: AnamneseCreate
) -> AnamneseDetail:
    anamnese = await anamnese_queries.buscar_por_id(db, anamnese_id)
    if anamnese is None or anamnese.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError
    validar_respostas(QUESTIONARIO_VIGENTE, payload)
    anamnese = await anamnese_queries.atualizar(
        db, anamnese, _respostas_para_persistir(QUESTIONARIO_VIGENTE, payload)
    )
    return _para_detalhe(anamnese)


async def deletar_anamnese(db: AsyncSession, paciente_id: int, anamnese_id: int) -> None:
    anamnese = await anamnese_queries.buscar_por_id(db, anamnese_id)
    if anamnese is None or anamnese.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError
    await anamnese_queries.deletar(db, anamnese)
