"""Testes de integração end-to-end para os endpoints de autenticação (fastapi-users)."""

import pytest
from httpx import AsyncClient

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/jwt/login"
ME_URL = "/api/v1/users/me"


@pytest.mark.asyncio
async def test_register_patient_success(client: AsyncClient) -> None:
    """Testa cadastro de paciente via endpoint HTTP (status 201 + dados do usuário)."""
    payload = {
        "email": "mariana@hality.com",
        "password": "SenhaSegura123!",
        "name": "Mariana Oliveira",
        "phone": "(11) 97777-6666",
    }

    response = await client.post(REGISTER_URL, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "mariana@hality.com"
    assert data["name"] == "Mariana Oliveira"
    assert data["phone"] == "(11) 97777-6666"
    assert data["is_active"] is True
    assert "id" in data
    # Senha não deve ser retornada
    assert "password" not in data
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_register_patient_duplicate_email(client: AsyncClient) -> None:
    """Testa erro 400 ao tentar cadastrar paciente com e-mail já existente."""
    payload = {
        "email": "mariana_dup@hality.com",
        "password": "SenhaSegura123!",
        "name": "Mariana Oliveira",
    }

    response1 = await client.post(REGISTER_URL, json=payload)
    assert response1.status_code == 201

    response2 = await client.post(REGISTER_URL, json=payload)
    assert response2.status_code == 400


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient) -> None:
    """Testa login bem-sucedido via endpoint HTTP (status 200 + token JWT)."""
    # Registrar primeiro
    register_payload = {
        "email": "lucas@hality.com",
        "password": "SenhaCorreta123!",
        "name": "Lucas Santos",
    }
    await client.post(REGISTER_URL, json=register_payload)

    # Login via formulário (fastapi-users usa OAuth2PasswordRequestForm)
    login_data = {
        "username": "lucas@hality.com",
        "password": "SenhaCorreta123!",
    }
    response = await client.post(
        LOGIN_URL,
        data=login_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient) -> None:
    """Testa erro 400 ao tentar login com credenciais incorretas."""
    login_data = {
        "username": "invalido@hality.com",
        "password": "SenhaErrada",
    }
    response = await client.post(
        LOGIN_URL,
        data=login_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_me_success(client: AsyncClient) -> None:
    """Testa obtenção dos dados do usuário autenticado no endpoint /users/me."""
    # Registrar
    register_payload = {
        "email": "renata@hality.com",
        "password": "SenhaSegura123!",
        "name": "Renata Costa",
        "phone": "(11) 95555-4444",
    }
    await client.post(REGISTER_URL, json=register_payload)

    # Login
    login_data = {
        "username": "renata@hality.com",
        "password": "SenhaSegura123!",
    }
    login_response = await client.post(
        LOGIN_URL,
        data=login_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login_response.json()["access_token"]

    # Me
    headers = {"Authorization": f"Bearer {token}"}
    me_response = await client.get(ME_URL, headers=headers)

    assert me_response.status_code == 200
    user_data = me_response.json()
    assert user_data["name"] == "Renata Costa"
    assert user_data["email"] == "renata@hality.com"
    assert user_data["phone"] == "(11) 95555-4444"
    assert user_data["is_active"] is True


@pytest.mark.asyncio
async def test_get_me_unauthorized(client: AsyncClient) -> None:
    """Testa erro 401 ao acessar endpoint /users/me sem token ou com token inválido."""
    response = await client.get(ME_URL)
    assert response.status_code == 401

    invalid_headers = {"Authorization": "Bearer token-invalido"}
    invalid_response = await client.get(ME_URL, headers=invalid_headers)
    assert invalid_response.status_code == 401


@pytest.mark.asyncio
async def test_register_missing_name(client: AsyncClient) -> None:
    """Testa erro 422 ao tentar cadastrar sem o campo obrigatório 'name'."""
    payload = {
        "email": "sem_nome@hality.com",
        "password": "SenhaSegura123!",
    }

    response = await client.post(REGISTER_URL, json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_logout_success(client: AsyncClient) -> None:
    """Testa logout bem-sucedido (POST /auth/jwt/logout)."""
    # Registrar e logar
    register_payload = {
        "email": "logout@hality.com",
        "password": "SenhaSegura123!",
        "name": "Teste Logout",
    }
    await client.post(REGISTER_URL, json=register_payload)

    login_data = {
        "username": "logout@hality.com",
        "password": "SenhaSegura123!",
    }
    login_response = await client.post(
        LOGIN_URL,
        data=login_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = login_response.json()["access_token"]

    # Logout
    headers = {"Authorization": f"Bearer {token}"}
    logout_response = await client.post("/api/v1/auth/jwt/logout", headers=headers)
    assert logout_response.status_code == 200 or logout_response.status_code == 204
