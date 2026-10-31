"""Lexer da anamnese: recebe respostas "cruas" (como o app envia) e devolve
itens tipados e validados, prontos pra virar o JSON de `respostas` na tabela
anamnese.

A ideia é a mesma de um lexer de linguagem: cada `RespostaBruta` é um token
não classificado; junto com a `Pergunta` correspondente do questionário
ativo, descobrimos a que categoria (TipoPergunta) esse token pertence e
emitimos um token tipado (`ItemRespostaRegistrada`) com o tipo de valor
concreto (TipoValor) já resolvido - ou reportamos um erro léxico, se o valor
não bater com a gramática esperada pra aquele tipo de pergunta.

Centraliza aqui toda a lógica de "qual é o tipo dessa pergunta/resposta" -
tanto o catálogo estático de fallback quanto o catálogo vigente vindo do
banco (`anamnese_questionary.py`) usam o mesmo lexer, sem duplicar regras.
"""

from collections.abc import Callable

from app.schemas.anamnese import (
    AnamneseCreate,
    ItemRespostaRegistrada,
    Pergunta,
    Questionario,
    RespostaBruta,
    TipoPergunta,
    TipoValor,
)


class AnamneseValidationError(Exception):
    """Levantada quando o payload tem pergunta obrigatória ausente ou um
    valor que não bate com o tipo/escala esperado (issue #18 pede 400
    nesses casos)."""

    def __init__(self, erros: list[str]) -> None:
        self.erros = erros
        super().__init__("; ".join(erros))


def _normalizar_texto(valor: str) -> str:
    return valor.strip()


def _lex_boolean(pergunta: Pergunta, bruta: RespostaBruta) -> ItemRespostaRegistrada:
    valor_bruto = bruta.valor_bruto
    if isinstance(valor_bruto, bool):
        valor, des_resposta = valor_bruto, ("Sim" if valor_bruto else "Não")
    elif isinstance(valor_bruto, str):
        normalizado = _normalizar_texto(valor_bruto).lower()
        if normalizado in ("sim", "true", "1"):
            valor, des_resposta = True, valor_bruto
        elif normalizado in ("não", "nao", "false", "0"):
            valor, des_resposta = False, valor_bruto
        else:
            raise ValueError(f"valor fora do tipo esperado para '{pergunta.id}' (esperado boolean)")
    else:
        raise ValueError(f"valor fora do tipo esperado para '{pergunta.id}' (esperado boolean)")
    return ItemRespostaRegistrada(
        pergunta_id=pergunta.id,
        des_pergunta=pergunta.enunciado,
        tipo_pergunta=TipoPergunta.BOOLEAN,
        des_resposta=des_resposta,
        valor=valor,
        tipo_resposta=TipoValor.BOOL,
    )


def _lex_single_choice(pergunta: Pergunta, bruta: RespostaBruta) -> ItemRespostaRegistrada:
    valor_bruto = bruta.valor_bruto
    if not isinstance(valor_bruto, str):
        raise ValueError(f"valor fora do tipo esperado para '{pergunta.id}' (esperado texto)")
    escolha = _normalizar_texto(valor_bruto)
    if pergunta.opcoes and escolha not in pergunta.opcoes:
        raise ValueError(f"valor fora das opções válidas para '{pergunta.id}'")
    return ItemRespostaRegistrada(
        pergunta_id=pergunta.id,
        des_pergunta=pergunta.enunciado,
        tipo_pergunta=TipoPergunta.SINGLE_CHOICE,
        des_resposta=escolha,
        valor=escolha,
        tipo_resposta=TipoValor.STR,
    )


def _lex_text(pergunta: Pergunta, bruta: RespostaBruta) -> ItemRespostaRegistrada:
    valor_bruto = bruta.valor_bruto
    if not isinstance(valor_bruto, str) or not valor_bruto.strip():
        raise ValueError(f"valor fora do tipo esperado para '{pergunta.id}' (esperado texto)")
    texto = _normalizar_texto(valor_bruto)
    return ItemRespostaRegistrada(
        pergunta_id=pergunta.id,
        des_pergunta=pergunta.enunciado,
        tipo_pergunta=TipoPergunta.TEXT,
        des_resposta=texto,
        valor=texto,
        tipo_resposta=TipoValor.STR,
    )


def _lex_scale(pergunta: Pergunta, bruta: RespostaBruta) -> ItemRespostaRegistrada:
    valor_bruto = bruta.valor_bruto
    minimo = pergunta.escala_min if pergunta.escala_min is not None else 1
    maximo = pergunta.escala_max if pergunta.escala_max is not None else 5
    if isinstance(valor_bruto, bool):
        raise ValueError(f"valor fora da escala {minimo}-{maximo} para '{pergunta.id}'")
    if isinstance(valor_bruto, int):
        numero = valor_bruto
    elif isinstance(valor_bruto, str) and valor_bruto.strip().lstrip("-").isdigit():
        numero = int(valor_bruto.strip())
    else:
        raise ValueError(f"valor fora da escala {minimo}-{maximo} para '{pergunta.id}'")
    if not (minimo <= numero <= maximo):
        raise ValueError(f"valor fora da escala {minimo}-{maximo} para '{pergunta.id}'")
    return ItemRespostaRegistrada(
        pergunta_id=pergunta.id,
        des_pergunta=pergunta.enunciado,
        tipo_pergunta=TipoPergunta.SCALE,
        des_resposta=str(numero),
        valor=numero,
        tipo_resposta=TipoValor.INT,
    )


_LEXERS: dict[TipoPergunta, Callable[[Pergunta, RespostaBruta], ItemRespostaRegistrada]] = {
    TipoPergunta.BOOLEAN: _lex_boolean,
    TipoPergunta.SINGLE_CHOICE: _lex_single_choice,
    TipoPergunta.TEXT: _lex_text,
    TipoPergunta.SCALE: _lex_scale,
}


def lexar_resposta(pergunta: Pergunta, bruta: RespostaBruta) -> ItemRespostaRegistrada:
    """Classifica e valida uma única resposta crua contra a pergunta
    correspondente. Levanta ValueError com uma mensagem pronta pra virar
    erro de validação - quem orquestra o lote inteiro é `lexar_respostas`."""

    lexer = _LEXERS[pergunta.tipo]
    return lexer(pergunta, bruta)


def lexar_respostas(
    questionario: Questionario, payload: AnamneseCreate
) -> list[ItemRespostaRegistrada]:
    """Varre todas as perguntas do questionário ativo (igual um lexer varre
    a entrada), casando cada uma com a resposta crua correspondente do
    payload. Acumula todos os erros encontrados (pergunta obrigatória
    ausente, tipo incompatível, pergunta desconhecida) em vez de parar no
    primeiro, e só levanta `AnamneseValidationError` no final."""

    erros: list[str] = []
    itens: list[ItemRespostaRegistrada] = []
    if payload.versao_questionario != questionario.versao:
        erros.append(f"versão de questionário inválida: '{payload.versao_questionario}'")

    ids_recebidos = [r.pergunta_id for r in payload.respostas]
    duplicadas = {
        pergunta_id for pergunta_id in ids_recebidos if ids_recebidos.count(pergunta_id) > 1
    }
    for pergunta_id in sorted(duplicadas):
        erros.append(f"resposta duplicada para pergunta: '{pergunta_id}'")

    brutas_por_pergunta = {r.pergunta_id: r for r in payload.respostas}
    perguntas_por_id = {p.id: p for p in questionario.perguntas}

    for pergunta in questionario.perguntas:
        bruta = brutas_por_pergunta.get(pergunta.id)
        valor_ausente = bruta is None or bruta.valor_bruto is None or bruta.valor_bruto == ""
        if pergunta.obrigatoria and valor_ausente:
            erros.append(f"pergunta obrigatória ausente: '{pergunta.id}'")
            continue
        if bruta is None or valor_ausente:
            continue
        try:
            itens.append(lexar_resposta(pergunta, bruta))
        except ValueError as erro:
            erros.append(str(erro))

    for bruta in payload.respostas:
        if bruta.pergunta_id not in perguntas_por_id:
            erros.append(f"pergunta desconhecida: '{bruta.pergunta_id}'")

    if erros:
        raise AnamneseValidationError(erros)

    return itens
