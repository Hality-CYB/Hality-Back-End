from pydantic import BaseModel


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