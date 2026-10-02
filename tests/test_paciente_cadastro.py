"""Cadastro de paciente novo pelo profissional — POST /pacientes."""

from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.users import password_helper
from app.main import app
from app.models import PacienteProfissional, User
from app.schemas.paciente import SENHA_PADRAO_PACIENTE
from tests.conftest import CenarioAdmin, autenticar_como, executar_no_banco

client = TestClient(app)

AUTH_HEADERS = {"Authorization": "Bearer fake-token"}
PACIENTES_URL = "/api/v1/pacientes"


def _payload(cenario: CenarioAdmin, **extras: Any) -> dict[str, Any]:
    return {
        "nome": "Paciente Novo",
        "email": cenario.email("novo"),
        "telefone": "(51) 98888-7777",
        "senha": "senha-provisoria",
        **extras,
    }


def _buscar_por_email(email: str) -> tuple[User | None, list[PacienteProfissional]]:
    async def _buscar(db: AsyncSession) -> tuple[User | None, list[PacienteProfissional]]:
        usuario = await db.scalar(select(User).where(User.email == email))
        if usuario is None:
            return None, []
        vinculos = await db.scalars(
            select(PacienteProfissional).where(PacienteProfissional.paciente_id == usuario.id)
        )
        return usuario, list(vinculos)

    return executar_no_banco(_buscar)


def test_profissional_cadastra_paciente_ja_vinculado(cenario_admin: CenarioAdmin) -> None:
    autenticar_como(cenario_admin.profissional)
    payload = _payload(cenario_admin)

    resposta = client.post(PACIENTES_URL, json=payload, headers=AUTH_HEADERS)

    assert resposta.status_code == status.HTTP_201_CREATED
    corpo = resposta.json()
    assert corpo["paciente_nome"] == "Paciente Novo"
    assert corpo["paciente_email"] == payload["email"]
    assert corpo["ativo"] is True
    assert "senha" not in corpo and "hashed_password" not in corpo

    paciente, vinculos = _buscar_por_email(payload["email"])
    assert paciente is not None
    assert str(paciente.id) == corpo["paciente_id"]
    assert paciente.role == "paciente"
    assert paciente.is_active is True
    assert paciente.phone == "(51) 98888-7777"
    assert password_helper.verify_and_update("senha-provisoria", paciente.hashed_password)[0]
    assert [(v.profissional_id, v.ativo) for v in vinculos] == [
        (cenario_admin.profissional.id, True)
    ]


def test_sem_senha_usa_senha_padrao(cenario_admin: CenarioAdmin) -> None:
    autenticar_como(cenario_admin.profissional)
    payload = _payload(cenario_admin)
    del payload["senha"]

    resposta = client.post(PACIENTES_URL, json=payload, headers=AUTH_HEADERS)

    assert resposta.status_code == status.HTTP_201_CREATED
    paciente, _ = _buscar_por_email(payload["email"])
    assert paciente is not None
    assert password_helper.verify_and_update(SENHA_PADRAO_PACIENTE, paciente.hashed_password)[0]


def test_paciente_cadastrado_aparece_na_listagem_do_profissional(
    cenario_admin: CenarioAdmin,
) -> None:
    autenticar_como(cenario_admin.profissional)
    criado = client.post(PACIENTES_URL, json=_payload(cenario_admin), headers=AUTH_HEADERS)

    resposta = client.get(f"{PACIENTES_URL}/{criado.json()['paciente_id']}", headers=AUTH_HEADERS)

    assert resposta.status_code == status.HTTP_200_OK


def test_email_ja_cadastrado_retorna_409(cenario_admin: CenarioAdmin) -> None:
    autenticar_como(cenario_admin.profissional)
    payload = _payload(cenario_admin, email=cenario_admin.paciente.email.upper())

    resposta = client.post(PACIENTES_URL, json=payload, headers=AUTH_HEADERS)

    assert resposta.status_code == status.HTTP_409_CONFLICT
    assert resposta.json()["detail"] == "e-mail já cadastrado"
    _, vinculos = _buscar_por_email(cenario_admin.paciente.email)
    assert vinculos == []


@pytest.mark.parametrize("papel", ["paciente", "admin"])
def test_so_profissional_pode_cadastrar(cenario_admin: CenarioAdmin, papel: str) -> None:
    autenticar_como(getattr(cenario_admin, papel))
    payload = _payload(cenario_admin)

    resposta = client.post(PACIENTES_URL, json=payload, headers=AUTH_HEADERS)

    assert resposta.status_code == status.HTTP_403_FORBIDDEN
    assert _buscar_por_email(payload["email"])[0] is None


def test_sem_token_retorna_401(cenario_admin: CenarioAdmin) -> None:
    autenticar_como(cenario_admin.profissional)

    resposta = client.post(PACIENTES_URL, json=_payload(cenario_admin))

    assert resposta.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize(
    "extras",
    [
        {"senha": "curta"},
        {"nome": "A"},
        {"email": "nao-e-email"},
        {"role": "admin"},
        {"ativo": False},
    ],
)
def test_payload_invalido_retorna_422(cenario_admin: CenarioAdmin, extras: dict) -> None:
    autenticar_como(cenario_admin.profissional)

    resposta = client.post(
        PACIENTES_URL, json=_payload(cenario_admin, **extras), headers=AUTH_HEADERS
    )

    assert resposta.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
