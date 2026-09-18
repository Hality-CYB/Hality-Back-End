from pydantic import BaseModel


class ClassificacaoDiagnosticoCreate(BaseModel):
    codigo: str
    nome_exibicao: str
    ordem: int


class ClassificacaoDiagnosticoDetail(BaseModel):
    """Tabela de referência (lookup).

    `codigo` é o valor estável usado pela aplicação (ex: 'halito_normal',
    'halitose_intima', 'mau_halito_social'); `nome_exibicao` é o label amigável
    mostrado na UI; `ordem` é o nível de severidade (1 a 3).
    """

    id: int
    codigo: str
    nome_exibicao: str
    ordem: int
