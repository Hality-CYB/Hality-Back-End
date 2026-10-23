"""Regra de senha nova (app/core/senha.py) em todo lugar que define senha."""

import pytest
from pydantic import ValidationError

from app.core.senha import validar_senha_nova
from app.schemas.admin_usuario import AdminUsuarioCreate
from app.schemas.identity import InvitationConfirmRequest, PasswordRecoveryConfirm
from app.schemas.paciente import PacienteCreate
from app.schemas.user import PasswordUpdate, RegistroCreate

TOKEN = "t" * 32


@pytest.mark.parametrize(
    ("senha", "motivo"),
    [
        ("Abc1234", "8 caracteres"),
        ("abcdefg1", "maiúscula"),
        ("ABCDEFG1", "minúscula"),
        ("Abcdefgh", "número"),
        ("Hality1234", "senha padrão"),
    ],
)
def test_recusa_senha_fora_da_regra(senha: str, motivo: str) -> None:
    with pytest.raises(ValueError, match=motivo):
        validar_senha_nova(senha)


def test_aceita_senha_com_maiuscula_minuscula_e_numero() -> None:
    assert validar_senha_nova("Halitose2026") == "Halitose2026"


# Um construtor por ponto de entrada que define senha nova.
PONTOS_DE_ENTRADA = {
    "cadastro público": lambda senha: RegistroCreate(
        email="a@hality.com", password=senha, name="Ana", data_nascimento="1990-01-01"
    ),
    "troca no perfil": lambda senha: PasswordUpdate(senha_atual="x", nova_senha=senha),
    "redefinição": lambda senha: PasswordRecoveryConfirm(token=TOKEN, senha=senha),
    "aceite de convite": lambda senha: InvitationConfirmRequest(token=TOKEN, senha=senha),
    "criação pelo admin": lambda senha: AdminUsuarioCreate(
        nome="Ana", email="a@hality.com", role="paciente", senha=senha
    ),
    "cadastro pelo profissional": lambda senha: PacienteCreate(
        nome="Ana", email="a@hality.com", senha=senha, data_nascimento="1990-01-01"
    ),
}


@pytest.mark.parametrize("ponto", PONTOS_DE_ENTRADA)
def test_todo_ponto_de_entrada_aplica_a_regra(ponto: str) -> None:
    construir = PONTOS_DE_ENTRADA[ponto]

    construir("Halitose2026")
    with pytest.raises(ValidationError, match="maiúscula"):
        construir("halitose2026")


def test_senha_continua_opcional_onde_o_convite_substitui() -> None:
    assert AdminUsuarioCreate(nome="Ana", email="a@hality.com", role="paciente").senha is None
    assert (
        PacienteCreate(nome="Ana", email="a@hality.com", data_nascimento="1990-01-01").senha is None
    )
