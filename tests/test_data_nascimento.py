"""Data de nascimento obrigatória no cadastro de paciente e questionário sem idade."""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.schemas.paciente import PacienteCreate
from app.schemas.user import RegistroCreate
from tests.conftest import CONSENTIMENTOS_CADASTRO

REGISTER_URL = "/api/v1/auth/register"
AMANHA = (date.today() + timedelta(days=1)).isoformat()


@pytest.mark.parametrize(
    "construir",
    [
        lambda **extra: RegistroCreate(
            email="a@hality.com", password="Halitose2026", name="Ana", **extra
        ),
        lambda **extra: PacienteCreate(nome="Ana", email="a@hality.com", **extra),
    ],
    ids=["cadastro público", "cadastro pelo profissional"],
)
def test_data_de_nascimento_obrigatoria_e_valida(construir) -> None:
    assert construir(data_nascimento="1990-05-20").data_nascimento == date(1990, 5, 20)
    with pytest.raises(ValidationError, match="data_nascimento"):
        construir()
    with pytest.raises(ValidationError, match="futuro"):
        construir(data_nascimento=AMANHA)
    with pytest.raises(ValidationError, match="1900"):
        construir(data_nascimento="1899-12-31")


@pytest.mark.asyncio
async def test_cadastro_grava_e_devolve_a_data_de_nascimento(client: AsyncClient) -> None:
    corpo = {
        "email": "nascimento@hality.com",
        "password": "Halitose2026",
        "name": "Paciente Nascimento",
        "data_nascimento": "1988-04-12",
        "consentimentos": CONSENTIMENTOS_CADASTRO,
    }

    resposta = await client.post(REGISTER_URL, json=corpo)

    assert resposta.status_code == 201
    assert resposta.json()["data_nascimento"] == "1988-04-12"


@pytest.mark.asyncio
async def test_cadastro_sem_data_de_nascimento_da_422(client: AsyncClient) -> None:
    corpo = {
        "email": "sem.nascimento@hality.com",
        "password": "Halitose2026",
        "name": "Sem Nascimento",
        "consentimentos": CONSENTIMENTOS_CADASTRO,
    }

    assert (await client.post(REGISTER_URL, json=corpo)).status_code == 422
