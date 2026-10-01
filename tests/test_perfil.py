"""Perfil do próprio usuário — GET/PATCH /users/me (US-023: AC-34, AC-35, AC-36).

Roda na suíte SQLite em memória (fixtures `client`/`db_session` do conftest).
Como `get_db` é sobrescrito pela mesma sessão em todas as requests, os testes
de persistência chamam `db_session.expire_all()` antes de reler — força o
SELECT no banco em vez de devolver o objeto em cache no identity map.
"""

import uuid

import pytest
from fastapi_users.jwt import generate_jwt
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Profissional, User

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
ME_URL = "/api/v1/users/me"

SENHA = "SenhaSegura123!"


async def _registrar_e_logar(
    client: AsyncClient,
    db: AsyncSession,
    email: str,
    *,
    role: str | None = None,
) -> dict[str, str]:
    """Registra, opcionalmente troca o role direto no banco e devolve o header de auth."""
    await client.post(
        REGISTER_URL,
        json={"email": email, "password": SENHA, "name": "Nome Original", "phone": "1111"},
    )
    if role is not None:
        user = await db.scalar(select(User).where(User.email == email))
        user.role = role
        await db.commit()

    response = await client.post(LOGIN_URL, data={"username": email, "password": SENHA})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _buscar_usuario(db: AsyncSession, email: str) -> User:
    db.expire_all()
    return await db.scalar(select(User).where(User.email == email))


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_me_paciente_sem_bloco_profissional(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _registrar_e_logar(client, db_session, "pac@hality.com")

    response = await client.get(ME_URL, headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Nome Original"
    assert data["profissional"] is None
    assert "hashed_password" not in data
    assert "password" not in data


@pytest.mark.asyncio
async def test_get_me_profissional_sem_registro_devolve_bloco_vazio(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _registrar_e_logar(client, db_session, "prof@hality.com", role="profissional")

    response = await client.get(ME_URL, headers=headers)

    assert response.status_code == 200
    assert response.json()["profissional"] == {
        "registro_profissional": None,
        "especialidade": None,
        "vinculado_hality": False,
    }


# ---------------------------------------------------------------------------
# AC-34 — campos permitidos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "campo_proibido",
    [
        {"role": "admin"},
        {"id": str(uuid.uuid4())},
        {"is_superuser": True},
        {"is_active": False},
        {"is_verified": True},
        {"password": "OutraSenha123!"},
        {"email": "outro@hality.com"},
        {"hashed_password": "x"},
    ],
)
async def test_patch_me_rejeita_campos_privilegiados(
    client: AsyncClient, db_session: AsyncSession, campo_proibido: dict
) -> None:
    email = "priv@hality.com"
    headers = await _registrar_e_logar(client, db_session, email)
    antes = await _buscar_usuario(db_session, email)
    estado_antes = (antes.id, antes.role, antes.is_superuser, antes.is_active, antes.email)
    hash_antes = antes.hashed_password

    response = await client.patch(
        ME_URL, headers=headers, json={"name": "Nome Novo", **campo_proibido}
    )

    assert response.status_code == 422
    depois = await _buscar_usuario(db_session, email)
    assert (depois.id, depois.role, depois.is_superuser, depois.is_active, depois.email) == (
        estado_antes
    )
    assert depois.hashed_password == hash_antes
    # Payload rejeitado inteiro: nem o campo permitido foi aplicado.
    assert depois.name == "Nome Original"


@pytest.mark.asyncio
async def test_patch_me_rejeita_vinculado_hality(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _registrar_e_logar(client, db_session, "vinc@hality.com", role="profissional")

    response = await client.patch(
        ME_URL, headers=headers, json={"profissional": {"vinculado_hality": True}}
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"name": "A"},
        {"name": None},
        {"name": "   "},
        {"name": "x" * 256},
        {"phone": "9" * 21},
        {"profissional": {"registro_profissional": "x" * 51}},
        {"profissional": {"especialidade": "x" * 101}},
    ],
)
async def test_patch_me_valida_campos(
    client: AsyncClient, db_session: AsyncSession, payload: dict
) -> None:
    headers = await _registrar_e_logar(client, db_session, "val@hality.com", role="profissional")

    response = await client.patch(ME_URL, headers=headers, json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_me_paciente_nao_envia_dados_profissionais(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _registrar_e_logar(client, db_session, "pac2@hality.com")

    response = await client.patch(
        ME_URL, headers=headers, json={"profissional": {"especialidade": "Dermatologia"}}
    )

    assert response.status_code == 403
    assert await db_session.scalar(select(Profissional)) is None


# ---------------------------------------------------------------------------
# AC-35 — persistência
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_me_persiste_nome_e_telefone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "persist@hality.com"
    headers = await _registrar_e_logar(client, db_session, email)

    response = await client.patch(
        ME_URL, headers=headers, json={"name": "  Nome Novo  ", "phone": "(11) 98888-7777"}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Nome Novo"

    usuario = await _buscar_usuario(db_session, email)
    assert usuario.name == "Nome Novo"
    assert usuario.phone == "(11) 98888-7777"

    recarregado = await client.get(ME_URL, headers=headers)
    assert recarregado.json()["name"] == "Nome Novo"
    assert recarregado.json()["phone"] == "(11) 98888-7777"


@pytest.mark.asyncio
async def test_patch_me_e_parcial(client: AsyncClient, db_session: AsyncSession) -> None:
    email = "parcial@hality.com"
    headers = await _registrar_e_logar(client, db_session, email)

    response = await client.patch(ME_URL, headers=headers, json={"phone": "2222"})

    assert response.status_code == 200
    usuario = await _buscar_usuario(db_session, email)
    assert usuario.phone == "2222"
    assert usuario.name == "Nome Original"


@pytest.mark.asyncio
async def test_patch_me_limpa_telefone_com_null(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "semfone@hality.com"
    headers = await _registrar_e_logar(client, db_session, email)

    response = await client.patch(ME_URL, headers=headers, json={"phone": None})

    assert response.status_code == 200
    assert (await _buscar_usuario(db_session, email)).phone is None


@pytest.mark.asyncio
async def test_patch_me_persiste_dados_profissionais(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "cro@hality.com"
    headers = await _registrar_e_logar(client, db_session, email, role="profissional")

    primeiro = await client.patch(
        ME_URL,
        headers=headers,
        json={"profissional": {"registro_profissional": "CRO-SP 12345", "especialidade": "Orto"}},
    )
    assert primeiro.status_code == 200

    # Segundo update parcial: altera só a especialidade, mantém o registro.
    segundo = await client.patch(
        ME_URL, headers=headers, json={"profissional": {"especialidade": "Periodontia"}}
    )
    assert segundo.status_code == 200

    usuario = await _buscar_usuario(db_session, email)
    profissional = await db_session.get(Profissional, usuario.id)
    assert profissional.registro_profissional == "CRO-SP 12345"
    assert profissional.especialidade == "Periodontia"
    assert profissional.vinculado_hality is False

    recarregado = await client.get(ME_URL, headers=headers)
    assert recarregado.json()["profissional"] == {
        "registro_profissional": "CRO-SP 12345",
        "especialidade": "Periodontia",
        "vinculado_hality": False,
    }


@pytest.mark.asyncio
async def test_perfil_persistido_aparece_apos_refresh(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _registrar_e_logar(client, db_session, "renova@hality.com")
    await client.patch(ME_URL, headers=headers, json={"name": "Nome Renovado"})
    db_session.expire_all()

    novo_token = (await client.post(REFRESH_URL)).json()["access_token"]
    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {novo_token}"})

    assert response.status_code == 200
    assert response.json()["name"] == "Nome Renovado"


# ---------------------------------------------------------------------------
# Isolamento
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_me_altera_apenas_o_proprio_usuario(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers_a = await _registrar_e_logar(client, db_session, "a@hality.com")
    headers_b = await _registrar_e_logar(client, db_session, "b@hality.com")

    await client.patch(ME_URL, headers=headers_a, json={"name": "Usuario A", "phone": "3333"})

    usuario_b = await _buscar_usuario(db_session, "b@hality.com")
    assert usuario_b.name == "Nome Original"
    assert usuario_b.phone == "1111"
    assert (await client.get(ME_URL, headers=headers_b)).json()["name"] == "Nome Original"


# ---------------------------------------------------------------------------
# AC-36 — sessão expirada
# ---------------------------------------------------------------------------


def _token_expirado(user_id: uuid.UUID) -> str:
    return generate_jwt(
        {"sub": str(user_id), "aud": ["fastapi-users:auth"]},
        get_settings().secret_key.get_secret_value(),
        lifetime_seconds=-60,
    )


@pytest.mark.asyncio
async def test_token_expirado_retorna_401_e_nao_altera(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "expirado@hality.com"
    await _registrar_e_logar(client, db_session, email)
    usuario = await _buscar_usuario(db_session, email)
    headers = {"Authorization": f"Bearer {_token_expirado(usuario.id)}"}

    leitura = await client.get(ME_URL, headers=headers)
    escrita = await client.patch(ME_URL, headers=headers, json={"name": "Nome Invasor"})

    assert leitura.status_code == 401
    assert escrita.status_code == 401
    assert (await _buscar_usuario(db_session, email)).name == "Nome Original"


@pytest.mark.asyncio
async def test_patch_me_sem_token_retorna_401(client: AsyncClient) -> None:
    response = await client.patch(ME_URL, json={"name": "Nome Novo"})
    assert response.status_code == 401
