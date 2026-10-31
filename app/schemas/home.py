import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.conteudo import CategoriaConteudo, ConteudoSchema
from app.schemas.diagnostico import StatusDiagnostico


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
    status: StatusDiagnostico
    classificacao: HomeClassificacao | None
    escala_saburra: int | None


class HomeDica(BaseModel):
    id: int
    titulo: str
    categoria: CategoriaConteudo
    conteudo: ConteudoSchema


class HomeResponse(BaseModel):
    usuario: HomeUsuario
    ultimo_diagnostico: HomeUltimoDiagnostico | None
    dicas: list[HomeDica]
