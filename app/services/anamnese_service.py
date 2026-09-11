from app.db.anamnese_store import AnamneseRecord, AnamneseRepository
from app.schemas.anamnese import (
    AnamneseCreate,
    AnamneseCreated,
    AnamneseDetail,
    Pergunta,
    Questionario,
    TipoPergunta,
)
from app.services.anamnese_questionnaire import get_questionario_ativo


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
            if pergunta.opcoes and valor not in pergunta.opcoes:
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


def _para_detalhe(registro: AnamneseRecord) -> AnamneseDetail:
    return AnamneseDetail(
        id=registro.id,
        paciente_id=registro.paciente_id,
        data_preenchimento=registro.data_preenchimento,
        versao_questionario=registro.versao_questionario,
        respostas=registro.respostas,
    )


def criar_anamnese(
    repo: AnamneseRepository, paciente_id: int, payload: AnamneseCreate
) -> AnamneseCreated:
    validar_respostas(get_questionario_ativo(), payload)
    registro = repo.salvar(
        paciente_id=paciente_id,
        versao_questionario=payload.versao_questionario,
        respostas=payload.respostas,
    )
    return AnamneseCreated(
        id=registro.id,
        paciente_id=registro.paciente_id,
        data_preenchimento=registro.data_preenchimento,
    )


def listar_anamneses(repo: AnamneseRepository, paciente_id: int) -> list[AnamneseDetail]:
    registros = repo.listar_por_paciente(paciente_id)
    registros.sort(key=lambda r: r.data_preenchimento, reverse=True)
    return [_para_detalhe(r) for r in registros]


def obter_anamnese(repo: AnamneseRepository, paciente_id: int, anamnese_id: int) -> AnamneseDetail:
    registro = repo.obter_por_id(anamnese_id)
    if registro is None or registro.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError
    return _para_detalhe(registro)


def atualizar_anamnese(
    repo: AnamneseRepository, paciente_id: int, anamnese_id: int, payload: AnamneseCreate
) -> AnamneseDetail:
    registro = repo.obter_por_id(anamnese_id)
    if registro is None or registro.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError
    validar_respostas(get_questionario_ativo(), payload)
    atualizado = repo.atualizar(
        anamnese_id=anamnese_id,
        versao_questionario=payload.versao_questionario,
        respostas=payload.respostas,
    )
    if atualizado is None:
        raise AnamneseNaoEncontradaError
    return _para_detalhe(atualizado)


def deletar_anamnese(repo: AnamneseRepository, paciente_id: int, anamnese_id: int) -> None:
    registro = repo.obter_por_id(anamnese_id)
    if registro is None or registro.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError
    repo.deletar(anamnese_id)
