"""Testes de integração end-to-end para os endpoints de autenticação."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_patient_endpoint_success(client: AsyncClient) -> None:
    """Testa cadastro de paciente via endpoint HTTP (status 201 + token JWT)."""
    payload = {
        "name": "Mariana Oliveira",
        "email": "mariana@hality.com",
        "phone": "(11) 97777-6666",
        "password": "SenhaSegura123",
    }

    response = await client.post("/api/v1/auth/register-patient", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_patient_endpoint_duplicate_email(client: AsyncClient) -> None:
    """Testa erro 400 ao tentar cadastrar paciente com e-mail já existente."""
    payload = {
        "name": "Mariana Oliveira",
        "email": "mariana_dup@hality.com",
        "password": "SenhaSegura123",
    }

    response1 = await client.post("/api/v1/auth/register-patient", json=payload)
    assert response1.status_code == 201

    response2 = await client.post("/api/v1/auth/register-patient", json=payload)
    assert response2.status_code == 400
    assert response2.json()["detail"] == "E-mail já cadastrado."


@pytest.mark.asyncio
async def test_login_endpoint_success(client: AsyncClient) -> None:
    """Testa login bem-sucedido via endpoint HTTP (status 200 + token JWT)."""
    register_payload = {
        "name": "Lucas Santos",
        "email": "lucas@hality.com",
        "password": "SenhaCorreta123",
    }
    await client.post("/api/v1/auth/register-patient", json=register_payload)

    login_payload = {
        "email": "lucas@hality.com",
        "password": "SenhaCorreta123",
    }
    response = await client.post("/api/v1/auth/login", json=login_payload)

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_endpoint_invalid_credentials(client: AsyncClient) -> None:
    """Testa erro 401 ao tentar login com credenciais incorretas."""
    login_payload = {
        "email": "invalido@hality.com",
        "password": "SenhaErrada",
    }
    response = await client.post("/api/v1/auth/login", json=login_payload)

    assert response.status_code == 401
    assert response.json()["detail"] == "E-mail ou senha incorretos."


@pytest.mark.asyncio
async def test_get_me_endpoint_success(client: AsyncClient) -> None:
    """Testa obtenção dos dados do usuário autenticado no endpoint /me."""
    register_payload = {
        "name": "Renata Costa",
        "email": "renata@hality.com",
        "phone": "(11) 95555-4444",
        "password": "SenhaSegura123",
    }
    reg_response = await client.post("/api/v1/auth/register-patient", json=register_payload)
    token = reg_response.json()["access_token"]

    headers = {"Authorization": f"Bearer {token}"}
    me_response = await client.get("/api/v1/auth/me", headers=headers)

    assert me_response.status_code == 200
    user_data = me_response.json()
    assert user_data["name"] == "Renata Costa"
    assert user_data["email"] == "renata@hality.com"
    assert user_data["phone"] == "(11) 95555-4444"
    assert user_data["role"] == "patient"
    assert user_data["is_active"] is True


@pytest.mark.asyncio
async def test_get_me_endpoint_unauthorized(client: AsyncClient) -> None:
    """Testa erro 401 ao acessar endpoint /me sem token ou com token inválido."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401

    invalid_headers = {"Authorization": "Bearer token-invalido"}
    invalid_response = await client.get("/api/v1/auth/me", headers=invalid_headers)
    assert invalid_response.status_code == 401
