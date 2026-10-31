"""Erros públicos do diagnóstico: a API expõe só código + mensagem daqui,
nunca o detalhe interno gravado em `diagnosticos.erro`."""

from dataclasses import dataclass
from enum import StrEnum


class CodigoErroDiagnostico(StrEnum):
    CLASSIFICACAO_NAO_CONFIGURADA = "classificacao_nao_configurada"
    FALHA_PROCESSAMENTO = "falha_processamento"
    LEGADO_SEM_CODIGO = "legado_sem_codigo"


_MENSAGEM_GENERICA = "Não foi possível concluir a análise da imagem."

MENSAGENS: dict[CodigoErroDiagnostico, str] = {
    CodigoErroDiagnostico.CLASSIFICACAO_NAO_CONFIGURADA: (
        "A análise está temporariamente indisponível. Tente novamente mais tarde."
    ),
    CodigoErroDiagnostico.FALHA_PROCESSAMENTO: _MENSAGEM_GENERICA,
    CodigoErroDiagnostico.LEGADO_SEM_CODIGO: _MENSAGEM_GENERICA,
}


@dataclass(frozen=True, slots=True)
class ErroPublico:
    codigo: CodigoErroDiagnostico
    mensagem: str


def erro_publico(status: str, erro_codigo: str | None) -> ErroPublico | None:
    if status != "falha":
        return None

    try:
        codigo = CodigoErroDiagnostico(erro_codigo)
    except ValueError:
        codigo = CodigoErroDiagnostico.FALHA_PROCESSAMENTO

    return ErroPublico(codigo=codigo, mensagem=MENSAGENS[codigo])
