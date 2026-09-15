"""Testes de integração end-to-end para os endpoints de autenticação."""

import pytest
from httpx import AsyncClient

# fastapi-users usa /auth/register (JSON) e /auth/login (form-data com campo 'username')
REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/users/me"

_DEFAULT_USER = {
    "email": "mariana@hality.com",
    "password": "SenhaSegura123!",
    "name": "Mariana Oliveira",
    "phone": "(11) 97777-6666",
}


async def _register_and_login(client: AsyncClient, user: dict | None = None) -> str:
    """Helper: registra um usuário e retorna o valor do cookie 'fastapiusersauth' do login."""
    user = user or _DEFAULT_USER
    await client.post(REGISTER_URL, json=user)
    # Login usa OAuth2PasswordRequestForm (form-data, campo 'username' em vez de 'email')
    response = await client.post(
        LOGIN_URL,
        data={"username": user["email"], "password": user["password"]},
    )
    return response.cookies.get("fastapiusersauth")


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_patient_success(client: AsyncClient) -> None:
    """Testa cadastro de paciente via endpoint HTTP (status 201 + dados do usuário)."""
    response = await client.post(REGISTER_URL, json=_DEFAULT_USER)

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == _DEFAULT_USER["email"]
    assert data["name"] == _DEFAULT_USER["name"]
    assert data["phone"] == _DEFAULT_USER["phone"]
    assert data["is_active"] is True
    assert "id" in data
    assert "password" not in data
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_register_patient_duplicate_email(client: AsyncClient) -> None:
    """Testa erro 400 ao tentar cadastrar com e-mail já existente."""
    payload = {"email": "dup@hality.com", "password": "SenhaSegura123!", "name": "Dup User"}
    await client.post(REGISTER_URL, json=payload)
    response = await client.post(REGISTER_URL, json=payload)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_register_missing_name(client: AsyncClient) -> None:
    """Testa erro 422 ao tentar cadastrar sem o campo obrigatório 'name'."""
    payload = {"email": "sem_nome@hality.com", "password": "SenhaSegura123!"}
    response = await client.post(REGISTER_URL, json=payload)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient) -> None:
    """Testa login bem-sucedido via form-data (status 200 + cookie fastapiusersauth)."""
    user = {"email": "lucas@hality.com", "password": "SenhaCorreta123!", "name": "Lucas Santos"}
    await client.post(REGISTER_URL, json=user)

    # fastapi-users usa OAuth2PasswordRequestForm: campo 'username' (não 'email')
    response = await client.post(
        LOGIN_URL,
        data={"username": user["email"], "password": user["password"]},
    )

    assert response.status_code == 204
    assert "fastapiusersauth" in response.cookies


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient) -> None:
    """Testa erro 400 ao tentar login com credenciais incorretas."""
    response = await client.post(
        LOGIN_URL,
        data={"username": "invalido@hality.com", "password": "SenhaErrada"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# /users/me
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_me_success(client: AsyncClient) -> None:
    """Testa obtenção dos dados do usuário autenticado no endpoint /users/me."""
    user = {
        "email": "renata@hality.com",
        "password": "SenhaSegura123!",
        "name": "Renata Costa",
        "phone": "(11) 95555-4444",
    }
    token = await _register_and_login(client, user)

    response = await client.get(ME_URL, cookies={"fastapiusersauth": token})

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Renata Costa"
    assert data["email"] == "renata@hality.com"
    assert data["phone"] == "(11) 95555-4444"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_get_me_unauthorized_no_token(client: AsyncClient) -> None:
    """Testa erro 401 ao acessar /users/me sem token."""
    response = await client.get(ME_URL)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me_unauthorized_invalid_token(client: AsyncClient) -> None:
    """Testa erro 401 ao acessar /users/me com token inválido no cookie."""
    response = await client.get(ME_URL, cookies={"fastapiusersauth": "token-invalido"})
    assert response.status_code == 401
