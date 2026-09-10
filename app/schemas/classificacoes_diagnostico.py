from pydantic import BaseModel


class ClassificacaoDiagnosticoCreate(BaseModel):
    codigo: str
    nome_exibicao: str
    ordem: int


class ClassificacaoDiagnosticoDetail(BaseModel):
    """Tabela de referência (lookup).

    `codigo` é o valor estável usado pela aplicação (ex: 'saudavel',
    'mau_halito', 'halitose_social'); `nome_exibicao` é o label amigável
    mostrado na UI; `ordem` é a ordem de severidade usada para ordenar na UI.
    """

    id: int
    codigo: str
    nome_exibicao: str
    ordem: int
