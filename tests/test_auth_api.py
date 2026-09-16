"""Testes de integração end-to-end para os endpoints de autenticação."""

import pytest
from httpx import AsyncClient

# fastapi-users usa /auth/register (JSON) e /auth/login (form-data com campo 'username')
REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/users/me"

# O refresh_token vive só num cookie httpOnly (nunca no corpo da resposta).
# `AsyncClient` mantém um cookie jar entre chamadas do mesmo `client`, então
# na maioria dos testes ele viaja sozinho — só é lido/sobrescrito
# manualmente quando o teste precisa provar algo sobre o valor específico
# (rotação, reuso, logout).
REFRESH_COOKIE_NAME = "refresh_token"

_DEFAULT_USER = {
    "email": "mariana@hality.com",
    "password": "SenhaSegura123!",
    "name": "Mariana Oliveira",
    "phone": "(11) 97777-6666",
}


async def _register_and_login(client: AsyncClient, user: dict | None = None) -> str:
    """Helper: registra um usuário, loga (cookie de refresh fica no client) e
    retorna o access_token."""
    user = user or _DEFAULT_USER
    await client.post(REGISTER_URL, json=user)
    # Login usa OAuth2PasswordRequestForm (form-data, campo 'username' em vez de 'email')
    response = await client.post(
        LOGIN_URL,
        data={"username": user["email"], "password": user["password"]},
    )
    return response.json()["access_token"]


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
    """Testa login bem-sucedido via form-data (status 200 + token JWT)."""
    user = {"email": "lucas@hality.com", "password": "SenhaCorreta123!", "name": "Lucas Santos"}
    await client.post(REGISTER_URL, json=user)

    # fastapi-users usa OAuth2PasswordRequestForm: campo 'username' (não 'email')
    response = await client.post(
        LOGIN_URL,
        data={"username": user["email"], "password": user["password"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" not in data
    assert data["token_type"] == "bearer"
    assert REFRESH_COOKIE_NAME in response.cookies
    assert response.cookies[REFRESH_COOKIE_NAME]

    # Trava os atributos do cookie — se alguém remover HttpOnly ou o Path
    # restrito por engano num refactor futuro, é aqui que quebra.
    set_cookie = response.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie
    assert "samesite=lax" in set_cookie.lower()


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

    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

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
    """Testa erro 401 ao acessar /users/me com token inválido."""
    response = await client.get(ME_URL, headers={"Authorization": "Bearer token-invalido"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Refresh e logout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_success(client: AsyncClient) -> None:
    """Refresh válido (cookie enviado automaticamente) devolve access token novo."""
    user = {"email": "paulo@hality.com", "password": "SenhaSegura123!", "name": "Paulo Reis"}
    await _register_and_login(client, user)

    response = await client.post(REFRESH_URL)

    assert response.status_code == 200
    novo = response.json()
    assert "access_token" in novo
    assert "refresh_token" not in novo
    assert REFRESH_COOKIE_NAME in response.cookies

    me = await client.get(ME_URL, headers={"Authorization": f"Bearer {novo['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == user["email"]


@pytest.mark.asyncio
async def test_refresh_rotacao_invalida_cookie_antigo(client: AsyncClient) -> None:
    """Depois de um refresh, o cookie antigo não pode ser reusado (rotação)."""
    user = {"email": "sofia@hality.com", "password": "SenhaSegura123!", "name": "Sofia Lima"}
    await _register_and_login(client, user)
    cookie_antigo = client.cookies.get(REFRESH_COOKIE_NAME)

    primeiro = await client.post(REFRESH_URL)
    assert primeiro.status_code == 200

    # client.cookies já foi atualizado pro cookie novo (rotacionado) pela
    # resposta acima — sobrescreve com o antigo pra provar que ele morreu.
    client.cookies.set(REFRESH_COOKIE_NAME, cookie_antigo)
    reuso = await client.post(REFRESH_URL)
    assert reuso.status_code == 401


@pytest.mark.asyncio
async def test_refresh_sem_cookie(client: AsyncClient) -> None:
    """Refresh sem nenhum cookie de sessão devolve 401."""
    response = await client.post(REFRESH_URL)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_com_cookie_invalido(client: AsyncClient) -> None:
    """Refresh com cookie que nunca existiu devolve 401."""
    client.cookies.set(REFRESH_COOKIE_NAME, "nao-existe")
    response = await client.post(REFRESH_URL)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_invalida_refresh_token(client: AsyncClient) -> None:
    """Logout apaga o refresh_token do banco — usar o cookie depois falha."""
    user = {"email": "bianca@hality.com", "password": "SenhaSegura123!", "name": "Bianca Alves"}
    await _register_and_login(client, user)
    cookie = client.cookies.get(REFRESH_COOKIE_NAME)

    logout = await client.post(LOGOUT_URL)
    assert logout.status_code == 204

    client.cookies.set(REFRESH_COOKIE_NAME, cookie)
    refresh_apos_logout = await client.post(REFRESH_URL)
    assert refresh_apos_logout.status_code == 401
