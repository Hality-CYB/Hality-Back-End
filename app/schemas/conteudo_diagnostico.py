from enum import StrEnum

from pydantic import BaseModel


class TipoConteudo(StrEnum):
    DICA = "dica"
    PROTOCOLO = "protocolo"


class DadosDica(BaseModel):
    tipo_midia: str
    corpo: str


class DadosProtocolo(BaseModel):
    numero_sessoes: int
    descricao: str


class ConteudoDiagnosticoCreate(BaseModel):
    """[substituiu protocolos_tratamento + dicas_tratamento - sugestao Discord]

    `classificacao_id` = None quando o conteúdo é genérico, não ligado a uma
    classificação de diagnóstico específica. O formato de `dados` depende de
    `tipo` e é resolvido em tempo de execução pela aplicação.
    """

    classificacao_id: int | None = None
    tipo: TipoConteudo
    titulo: str
    dados: DadosDica | DadosProtocolo


class ConteudoDiagnosticoDetail(BaseModel):
    id: int
    classificacao_id: int | None = None
    tipo: TipoConteudo
    titulo: str
    dados: DadosDica | DadosProtocolo