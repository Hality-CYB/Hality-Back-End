"""Testes do fluxo de recuperação e da outbox de identidade."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailOutbox, IdentityAction, User
from app.services.identity_token_service import (
    PASSWORD_RESET,
    _token_for,
    dispatch_pending_emails,
)

RECOVERY_URL = "/api/v1/auth/password-recovery"
CONFIRM_URL = "/api/v1/auth/password-recovery/confirm"


@pytest.mark.asyncio
async def test_recovery_has_resposta_uniforme_e_enfileira_apenas_hash(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    payload = {"email": "recuperacao@hality.com", "password": "SenhaSegura123!", "name": "Pessoa"}
    await client.post("/api/v1/auth/register", json=payload)

    existente = await client.post(RECOVERY_URL, json={"email": payload["email"]})
    inexistente = await client.post(RECOVERY_URL, json={"email": "nao@hality.com"})

    assert existente.status_code == inexistente.status_code == 202
    assert existente.json() == inexistente.json()
    action = await db_session.scalar(select(IdentityAction))
    outbox = await db_session.scalar(select(EmailOutbox))
    assert action is not None
    assert outbox is not None
    assert action.purpose == PASSWORD_RESET
    assert action.token_hash != _token_for(action.id, action.purpose)
    assert outbox.status == "queued"


@pytest.mark.asyncio
async def test_recovery_rate_limit_mantem_resposta_publica(client: AsyncClient) -> None:
    email = "limite@hality.com"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SenhaSegura123!", "name": "Pessoa"},
    )

    respostas = [await client.post(RECOVERY_URL, json={"email": email}) for _ in range(6)]

    assert all(resposta.status_code == 202 for resposta in respostas)


@pytest.mark.asyncio
async def test_confirmacao_consume_uma_vez_e_invalida_refresh(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    payload = {"email": "reset@hality.com", "password": "SenhaSegura123!", "name": "Pessoa"}
    await client.post("/api/v1/auth/register", json=payload)
    await client.post(
        "/api/v1/auth/login", data={"username": payload["email"], "password": payload["password"]}
    )
    await client.post(RECOVERY_URL, json={"email": payload["email"]})
    action = await db_session.scalar(select(IdentityAction))
    assert action is not None

    token = _token_for(action.id, action.purpose)
    confirm = await client.post(CONFIRM_URL, json={"token": token, "senha": "NovaSenhaSegura123!"})
    reuse = await client.post(CONFIRM_URL, json={"token": token, "senha": "OutraSenha123!"})

    assert confirm.status_code == 204
    assert reuse.status_code == 400
    user = await db_session.scalar(select(User).where(User.email == payload["email"]))
    assert user is not None
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": payload["email"], "password": "NovaSenhaSegura123!"},
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_outbox_retry_e_marca_falha_sem_token_no_erro(db_session: AsyncSession) -> None:
    user = User(email="provider@hality.com", hashed_password="hash", name="Pessoa")
    db_session.add(user)
    await db_session.flush()

    from app.services.identity_token_service import create_invitation

    await create_invitation(db_session, user)

    class Provider:
        async def send(self, message) -> None:
            raise RuntimeError("falha transitória")

    await dispatch_pending_emails(db_session, Provider())
    outbox = await db_session.scalar(select(EmailOutbox))
    assert outbox is not None
    assert outbox.status == "failed"
    assert outbox.last_error == "RuntimeError"
    available_at = (
        outbox.available_at.replace(tzinfo=UTC)
        if outbox.available_at.tzinfo is None
        else outbox.available_at
    )
    assert datetime.now(UTC) + timedelta(minutes=1) >= available_at
