import uuid
from datetime import datetime

from pydantic import BaseModel


class HomeUsuario(BaseModel):
    id: uuid.UUID
    nome: str
    tipo_usuario: str


class HomeClassificacao(BaseModel):
    codigo: str
    nome_exibicao: str


class HomeUltimoDiagnostico(BaseModel):
    id: int
    data_diagnostico: datetime
    status: str
    classificacao: HomeClassificacao | None
    escala_saburra: int | None


class DicaResumo(BaseModel):
    id: int
    titulo: str
    conteudo: str


class HomeResponse(BaseModel):
    usuario: HomeUsuario
    total_diagnosticos: int
    avisos_nao_lidos: int
    ultimo_diagnostico: HomeUltimoDiagnostico | None
    total_dicas: int
    dicas: list[DicaResumo]
