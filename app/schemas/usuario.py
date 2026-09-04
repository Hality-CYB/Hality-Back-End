from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class TipoUsuario(StrEnum):
    PACIENTE = "paciente"
    PROFISSIONAL = "profissional"
    ADMIN = "admin"


class UsuarioCreate(BaseModel):
    nome: str
    email: str
    telefone: str | None = None
    senha: str
    tipo_usuario: TipoUsuario


class UsuarioCreated(BaseModel):
    """Corpo de resposta do POST - não expõe senha_hash nem outros dados sensíveis."""

    id: int
    nome: str
    email: str
    tipo_usuario: TipoUsuario
    data_cadastro: datetime


class UsuarioDetail(BaseModel):
    id: int
    nome: str
    email: str
    telefone: str | None = None
    tipo_usuario: TipoUsuario
    data_cadastro: datetime
    ativo: bool


class UsuarioUpdate(BaseModel):
    """Todos os campos opcionais - usado num PATCH parcial."""

    nome: str | None = None
    telefone: str | None = None
    ativo: bool | None = None