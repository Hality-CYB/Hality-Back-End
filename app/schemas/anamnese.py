from datetime import datetime
from enum import StrEnum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class TipoPergunta(StrEnum):
    """Categoria "gramatical" da pergunta - o que o lexer usa pra decidir
    qual regra aplicar sobre o valor cru recebido."""

    BOOLEAN = "boolean"
    SINGLE_CHOICE = "single_choice"
    TEXT = "text"
    SCALE = "scale"


class TipoValor(StrEnum):
    """Tipo Python/JSON concreto do valor já resolvido pelo lexer.
    Não é 1:1 com TipoPergunta: SINGLE_CHOICE e TEXT resolvem pro mesmo
    TipoValor.STR, por exemplo."""

    BOOL = "bool"
    STR = "str"
    INT = "int"


class Pergunta(BaseModel):
    """Definição de uma pergunta do questionário (vem do catálogo ativo,
    seja ele o fallback estático ou uma fonte real no futuro)."""

    id: str
    enunciado: str
    tipo: TipoPergunta
    obrigatoria: bool = True
    opcoes: list[str] | None = None
    escala_min: int | None = None
    escala_max: int | None = None
    escala_label_min: str | None = None
    escala_label_max: str | None = None


class Questionario(BaseModel):
    """`versao` é o identificador que vira `id_versao_questionario` na
    anamnese registrada - hoje é uma string estática (catálogo fallback),
    mas o formato foi pensado pra aceitar um id vindo de uma fonte real
    (banco/CMS) no futuro sem quebrar contrato."""

    versao: str
    perguntas: list[Pergunta]


class RespostaBruta(BaseModel):
    """O que chega no corpo do POST: a resposta ainda "crua", exatamente
    como o app enviou (ex: "Sim"/"Não" pro boolean, "5" pra escala, o texto
    da opção escolhida pro single_choice). O cliente NÃO declara o tipo -
    isso é sempre resolvido a partir da pergunta correspondente, pelo lexer
    (`anamnese_lexer.py`)."""

    model_config = ConfigDict(extra="ignore")

    pergunta_id: str
    valor_bruto: str | bool | int = Field(
        validation_alias=AliasChoices("valor_bruto", "valor")
    )


class AnamneseCreate(BaseModel):
    versao_questionario: str = Field(
        validation_alias=AliasChoices("versao_questionario", "id_versao_questionario")
    )
    respostas: list[RespostaBruta]


class ItemRespostaRegistrada(BaseModel):
    """Um item já "lexado": pergunta e resposta resolvidas e tipadas, prontas
    pra ir pro campo JSON da anamnese. `des_pergunta`/`des_resposta` guardam
    o texto exatamente como foi perguntado/respondido (auditoria - sobrevive
    mesmo se o enunciado da pergunta mudar numa versão futura do
    questionário); `valor`/`tipo_resposta` guardam a forma tipada, usada pra
    qualquer leitura/filtro programático."""

    pergunta_id: str
    des_pergunta: str = Field(
        validation_alias=AliasChoices("des_pergunta", "enunciado"),
        serialization_alias="enunciado",
    )
    tipo_pergunta: TipoPergunta = Field(
        validation_alias=AliasChoices("tipo_pergunta", "tipo"),
        serialization_alias="tipo",
    )
    des_resposta: str = Field(
        validation_alias=AliasChoices("des_resposta", "resposta"),
        serialization_alias="resposta",
    )
    valor: bool | str | int
    tipo_resposta: TipoValor


class AnamneseCreated(BaseModel):
    """Corpo de resposta do POST, exatamente como especificado na issue #18."""

    id: int = Field(validation_alias=AliasChoices("id", "id_resp"))
    paciente_id: int
    data_preenchimento: datetime


class AnamneseDetail(BaseModel):
    """Usado nos GETs/PUT do CRUD, onde faz sentido devolver o conteúdo
    completo. Mapeia direto pras colunas da tabela anamnese: id_resp,
    id_versao_questionario e o JSON de respostas (des_pergunta/des_resposta
    + tipos)."""

    id: int = Field(validation_alias=AliasChoices("id", "id_resp"))
    paciente_id: int
    data_preenchimento: datetime
    versao_questionario: str = Field(
        validation_alias=AliasChoices("versao_questionario", "id_versao_questionario")
    )
    respostas: list[ItemRespostaRegistrada]
