"""Erros públicos do diagnóstico: a API expõe só código + mensagem daqui,
nunca o detalhe interno gravado em `diagnosticos.erro`. Exceção: em
`IMAGEM_REJEITADA`, o `erro` guarda a própria orientação que a IA devolve
ao usuário (ex.: "mostre a língua de frente"), que por ser texto voltado ao
usuário é promovida a mensagem pública."""

from dataclasses import dataclass
from enum import StrEnum


class CodigoErroDiagnostico(StrEnum):
    CLASSIFICACAO_NAO_CONFIGURADA = "classificacao_nao_configurada"
    FALHA_PROCESSAMENTO = "falha_processamento"
    IMAGEM_REJEITADA = "imagem_rejeitada"
    LEGADO_SEM_CODIGO = "legado_sem_codigo"


_MENSAGEM_GENERICA = "Não foi possível concluir a análise da imagem."
# Usada só quando a IA rejeita sem texto de orientação (não deveria acontecer).
_MENSAGEM_REJEICAO_PADRAO = (
    "Não consegui identificar a língua na foto. Siga as orientações de captura e tente de novo."
)

MENSAGENS: dict[CodigoErroDiagnostico, str] = {
    CodigoErroDiagnostico.CLASSIFICACAO_NAO_CONFIGURADA: (
        "A análise está temporariamente indisponível. Tente novamente mais tarde."
    ),
    CodigoErroDiagnostico.FALHA_PROCESSAMENTO: _MENSAGEM_GENERICA,
    CodigoErroDiagnostico.IMAGEM_REJEITADA: _MENSAGEM_REJEICAO_PADRAO,
    CodigoErroDiagnostico.LEGADO_SEM_CODIGO: _MENSAGEM_GENERICA,
}


@dataclass(frozen=True, slots=True)
class ErroPublico:
    codigo: CodigoErroDiagnostico
    mensagem: str


def erro_publico(
    status: str, erro_codigo: str | None, erro_interno: str | None = None
) -> ErroPublico | None:
    if status != "falha":
        return None

    try:
        codigo = CodigoErroDiagnostico(erro_codigo)
    except ValueError:
        codigo = CodigoErroDiagnostico.FALHA_PROCESSAMENTO

    # Imagem rejeitada: a orientação da IA (voltada ao usuário) é a mensagem
    # pública; cai no padrão se vier vazia. Os demais códigos nunca expõem o
    # `erro` interno — só a mensagem estática.
    if codigo is CodigoErroDiagnostico.IMAGEM_REJEITADA:
        mensagem = (erro_interno or "").strip() or MENSAGENS[codigo]
    else:
        mensagem = MENSAGENS[codigo]

    return ErroPublico(codigo=codigo, mensagem=mensagem)
