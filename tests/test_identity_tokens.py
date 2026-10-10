"""Testes do fluxo de recuperação e da outbox de identidade."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailOutbox, IdentityAction, User
from app.services.identity_token_service import (
    CONSUMED,
    EXPIRED,
    INVITATION,
    PASSWORD_RESET,
    SENT,
    _token_for,
    consume_invitation,
    create_invitation,
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
async def test_confirmacao_de_convite_publica(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "confirmar-convite@hality.com"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SenhaSegura123!", "name": "Pessoa"},
    )
    user = await db_session.scalar(select(User).where(User.email == email))
    assert user is not None
    await create_invitation(db_session, user)
    action = await db_session.scalar(
        select(IdentityAction).where(IdentityAction.purpose == INVITATION)
    )
    assert action is not None

    response = await client.post(
        "/api/v1/auth/invitation/confirm",
        json={"token": _token_for(action.id, action.purpose), "senha": "SenhaConvite123!"},
    )

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_outbox_retry_e_marca_falha_sem_token_no_erro(db_session: AsyncSession) -> None:
    user = User(email="provider@hality.com", hashed_password="hash", name="Pessoa")
    db_session.add(user)
    await db_session.flush()

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


@pytest.mark.asyncio
async def test_outbox_sucesso_e_consumo_de_convite(db_session: AsyncSession) -> None:
    user = User(email="convite@hality.com", hashed_password="hash", name="Pessoa")
    db_session.add(user)
    await db_session.flush()
    await create_invitation(db_session, user)

    messages = []

    class Provider:
        async def send(self, message) -> None:
            messages.append(message)

    assert await dispatch_pending_emails(db_session, Provider()) == 1
    outbox = await db_session.scalar(select(EmailOutbox))
    action = await db_session.scalar(select(IdentityAction))
    assert outbox is not None and action is not None
    assert outbox.status == SENT
    assert action.purpose == INVITATION
    assert messages[0].token != action.token_hash

    await consume_invitation(db_session, messages[0].token, "SenhaConvite123!")
    await db_session.refresh(outbox)
    assert outbox.status == CONSUMED


@pytest.mark.asyncio
async def test_outbox_marca_token_expirado_e_revogado(db_session: AsyncSession) -> None:
    user = User(email="expirado@hality.com", hashed_password="hash", name="Pessoa")
    db_session.add(user)
    await db_session.flush()
    await create_invitation(db_session, user)
    action = await db_session.scalar(select(IdentityAction))
    assert action is not None
    action.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    class Provider:
        async def send(self, message) -> None:
            raise AssertionError("token expirado não deve ser enviado")

    await dispatch_pending_emails(db_session, Provider())
    outbox = await db_session.scalar(select(EmailOutbox))
    assert outbox is not None and outbox.status == EXPIRED

    user = User(email="revogado@hality.com", hashed_password="hash", name="Pessoa")
    db_session.add(user)
    await db_session.flush()
    await create_invitation(db_session, user)
    action = await db_session.scalar(
        select(IdentityAction).where(IdentityAction.user_id == user.id)
    )
    assert action is not None
    action.revoked_at = datetime.now(UTC)
    await db_session.commit()
    await dispatch_pending_emails(db_session, Provider())
    outbox = await db_session.scalar(select(EmailOutbox).where(EmailOutbox.action_id == action.id))
    assert outbox is not None and outbox.status == EXPIRED
