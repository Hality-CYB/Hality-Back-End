"""Schemas Pydantic para autenticação e dados de usuário."""

import uuid

from fastapi_users import schemas
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.admin_usuario import SENHA_TAMANHO_MINIMO
from app.schemas.profissionais import ProfissionalPerfilRead, ProfissionalPerfilUpdate


class UserRead(schemas.BaseUser[uuid.UUID]):
    """Dados públicos do usuário retornados pela API.

    `profissional` só vem preenchido em `/users/me` para usuários com
    role = profissional — nunca carrega senha, hash ou token.
    """

    name: str
    phone: str | None = None
    role: str
    profissional: ProfissionalPerfilRead | None = None


class UserCreate(schemas.BaseUserCreate):
    """Dados enviados no cadastro de um novo usuário."""

    name: str = Field(..., min_length=2, max_length=255, examples=["Maria Silva"])
    phone: str | None = Field(None, max_length=20, examples=["(11) 99999-9999"])


class UserUpdate(BaseModel):
    """Payload do PATCH /users/me — só os campos que o próprio usuário pode alterar.

    Qualquer campo fora desta lista (papel, id, e-mail, senha, flags de status
    da conta, vinculado_hality...) é rejeitado com 422 em vez de ignorado em
    silêncio, para o FE nunca achar que alterou algo que não mudou.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(None, min_length=2, max_length=255)
    phone: str | None = Field(None, max_length=20)
    profissional: ProfissionalPerfilUpdate | None = None

    @model_validator(mode="after")
    def _nome_nao_pode_ser_nulo(self) -> "UserUpdate":
        # `name` é opcional no payload (update parcial), mas se vier tem que ter valor:
        # a coluna é NOT NULL.
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name não pode ser nulo")
        return self


class PasswordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    senha_atual: str = Field(..., min_length=1)
    nova_senha: str = Field(..., min_length=SENHA_TAMANHO_MINIMO)
