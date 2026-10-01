from pydantic import BaseModel, ConfigDict, Field


class ProfissionalCreate(BaseModel):
    """Extensão de UsuarioCreate, preenchida quando tipo_usuario = profissional."""

    registro_profissional: str | None = None  # [confirmar] CRO/CRM - obrigatorio?
    especialidade: str | None = None
    vinculado_hality: bool = False


class ProfissionalDetail(BaseModel):
    usuario_id: int
    registro_profissional: str | None = None
    especialidade: str | None = None
    vinculado_hality: bool


class ProfissionalPerfilRead(BaseModel):
    """Bloco profissional agregado na resposta de /users/me."""

    model_config = ConfigDict(from_attributes=True)

    registro_profissional: str | None = None
    especialidade: str | None = None
    vinculado_hality: bool = False


class ProfissionalPerfilUpdate(BaseModel):
    """Dados profissionais que o próprio profissional pode alterar.

    `vinculado_hality` fica de fora de propósito: é status concedido pela
    plataforma, não autodeclarado.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    registro_profissional: str | None = Field(None, max_length=50)
    especialidade: str | None = Field(None, max_length=100)
