import logging
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailOutbox, IdentityAction, RefreshToken, User
from app.services.identity_token_service import (
    EMAIL_VERIFICATION,
    EXPIRED,
    QUEUED,
    _token_for,
    dispatch_pending_emails,
)
from tests.conftest import CONSENTIMENTOS_CADASTRO

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
CONFIRM_URL = "/api/v1/auth/email-verification/confirm"
RESEND_URL = "/api/v1/auth/email-verification/resend"
SENHA = "SenhaSegura123!"


def _cadastro(email: str) -> dict:
    return {
        "email": email,
        "password": SENHA,
        "data_nascimento": "1990-01-01",
        "name": "Pessoa Pendente",
        "consentimentos": CONSENTIMENTOS_CADASTRO,
    }


async def _acoes_de_verificacao(db: AsyncSession, email: str) -> list[IdentityAction]:
    db.expire_all()
    return list(
        await db.scalars(
            select(IdentityAction)
            .join(User, User.id == IdentityAction.user_id)
            .where(User.email == email, IdentityAction.purpose == EMAIL_VERIFICATION)
            .order_by(IdentityAction.created_at)
        )
    )


async def _token_ativo(db: AsyncSession, email: str) -> str:
    acoes = [
        acao
        for acao in await _acoes_de_verificacao(db, email)
        if acao.used_at is None and acao.revoked_at is None
    ]
    assert len(acoes) == 1
    return _token_for(acoes[0].id, acoes[0].purpose)


async def _usuario(db: AsyncSession, email: str) -> User:
    db.expire_all()
    return await db.scalar(select(User).where(User.email == email))


def _login(client: AsyncClient, email: str, senha: str = SENHA):
    return client.post(LOGIN_URL, data={"username": email, "password": senha})


@pytest.mark.asyncio
async def test_cadastro_cria_conta_pendente_acao_e_outbox_sem_sessao(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "pendente@hality.com"

    resposta = await client.post(REGISTER_URL, json=_cadastro(email))

    assert resposta.status_code == 201
    assert "refresh_token" not in resposta.cookies
    assert "access_token" not in resposta.json()
    usuario = await _usuario(db_session, email)
    assert usuario.is_verified is False
    acoes = await _acoes_de_verificacao(db_session, email)
    assert len(acoes) == 1
    assert acoes[0].token_hash != _token_for(acoes[0].id, acoes[0].purpose)
    outbox = await db_session.scalar(
        select(EmailOutbox).where(EmailOutbox.action_id == acoes[0].id)
    )
    assert outbox.status == QUEUED
    assert outbox.purpose == EMAIL_VERIFICATION
    assert outbox.recipient_email == email


@pytest.mark.asyncio
async def test_login_antes_da_confirmacao_retorna_403_sem_sessao(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "sem-confirmar@hality.com"
    await client.post(REGISTER_URL, json=_cadastro(email))

    resposta = await _login(client, email)

    assert resposta.status_code == 403
    assert resposta.json()["detail"] == "EMAIL_NOT_VERIFIED"
    assert "access_token" not in resposta.json()
    assert 'refresh_token=""' in resposta.headers.get("set-cookie", "")
    assert await db_session.scalar(select(RefreshToken)) is None


@pytest.mark.asyncio
async def test_senha_errada_de_conta_pendente_continua_400(client: AsyncClient) -> None:
    email = "senha-errada@hality.com"
    await client.post(REGISTER_URL, json=_cadastro(email))

    resposta = await _login(client, email, "OutraSenha123!")

    assert resposta.status_code == 400


@pytest.mark.asyncio
async def test_confirmacao_libera_login_sem_emitir_sessao(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "confirma@hality.com"
    await client.post(REGISTER_URL, json=_cadastro(email))
    token = await _token_ativo(db_session, email)

    confirmacao = await client.post(CONFIRM_URL, json={"token": token})

    assert confirmacao.status_code == 204
    assert "set-cookie" not in confirmacao.headers
    assert (await _usuario(db_session, email)).is_verified is True
    login = await _login(client, email)
    assert login.status_code == 200
    assert "access_token" in login.json()


@pytest.mark.asyncio
async def test_confirmacao_altera_somente_a_conta_do_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.post(REGISTER_URL, json=_cadastro("dono@hality.com"))
    await client.post(REGISTER_URL, json=_cadastro("outro@hality.com"))
    token = await _token_ativo(db_session, "dono@hality.com")

    await client.post(CONFIRM_URL, json={"token": token})

    assert (await _usuario(db_session, "dono@hality.com")).is_verified is True
    assert (await _usuario(db_session, "outro@hality.com")).is_verified is False


@pytest.mark.asyncio
async def test_token_reutilizado_retorna_400(client: AsyncClient, db_session: AsyncSession) -> None:
    email = "reuso@hality.com"
    await client.post(REGISTER_URL, json=_cadastro(email))
    token = await _token_ativo(db_session, email)
    await client.post(CONFIRM_URL, json={"token": token})

    reuso = await client.post(CONFIRM_URL, json={"token": token})

    assert reuso.status_code == 400
    assert reuso.json()["detail"] == "TOKEN_DE_VERIFICACAO_INVALIDO"


@pytest.mark.asyncio
async def test_token_invalido_retorna_400(client: AsyncClient) -> None:
    resposta = await client.post(CONFIRM_URL, json={"token": "x" * 43})

    assert resposta.status_code == 400
    assert resposta.json()["detail"] == "TOKEN_DE_VERIFICACAO_INVALIDO"


@pytest.mark.asyncio
async def test_token_expirado_retorna_400_e_nao_verifica(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "expirado@hality.com"
    await client.post(REGISTER_URL, json=_cadastro(email))
    token = await _token_ativo(db_session, email)
    await db_session.execute(
        update(IdentityAction)
        .where(IdentityAction.purpose == EMAIL_VERIFICATION)
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db_session.commit()

    resposta = await client.post(CONFIRM_URL, json={"token": token})

    assert resposta.status_code == 400
    assert (await _usuario(db_session, email)).is_verified is False
    outbox = await db_session.scalar(select(EmailOutbox))
    assert outbox.status == EXPIRED


@pytest.mark.asyncio
async def test_token_de_outra_finalidade_nao_confirma(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "finalidade@hality.com"
    await client.post(REGISTER_URL, json=_cadastro(email))
    acao = (await _acoes_de_verificacao(db_session, email))[0]

    resposta = await client.post(CONFIRM_URL, json={"token": _token_for(acao.id, "password_reset")})

    assert resposta.status_code == 400
    assert (await _usuario(db_session, email)).is_verified is False


@pytest.mark.asyncio
async def test_link_expira_em_60_minutos(client: AsyncClient, db_session: AsyncSession) -> None:
    email = "validade@hality.com"
    antes = datetime.now(UTC)
    await client.post(REGISTER_URL, json=_cadastro(email))

    acao = (await _acoes_de_verificacao(db_session, email))[0]
    expira = acao.expires_at.replace(tzinfo=UTC)

    assert timedelta(minutes=59) < expira - antes <= timedelta(minutes=61)


@pytest.mark.asyncio
async def test_reenvio_revoga_link_anterior(client: AsyncClient, db_session: AsyncSession) -> None:
    email = "reenvio@hality.com"
    await client.post(REGISTER_URL, json=_cadastro(email))
    token_antigo = await _token_ativo(db_session, email)

    resposta = await client.post(RESEND_URL, json={"email": email})

    assert resposta.status_code == 202
    token_novo = await _token_ativo(db_session, email)
    assert token_novo != token_antigo
    assert (await client.post(CONFIRM_URL, json={"token": token_antigo})).status_code == 400
    assert (await client.post(CONFIRM_URL, json={"token": token_novo})).status_code == 204


@pytest.mark.asyncio
async def test_reenvio_tem_resposta_igual_para_endereco_inexistente_ou_verificado(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "ja-verificado@hality.com"
    await client.post(REGISTER_URL, json=_cadastro(email))
    await client.post(CONFIRM_URL, json={"token": await _token_ativo(db_session, email)})

    existente = await client.post(RESEND_URL, json={"email": email})
    inexistente = await client.post(RESEND_URL, json={"email": "ninguem@hality.com"})

    assert existente.status_code == inexistente.status_code == 202
    assert existente.json() == inexistente.json()
    assert len(await _acoes_de_verificacao(db_session, email)) == 1


@pytest.mark.asyncio
async def test_reenvio_limita_cinco_solicitacoes_por_janela(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "abuso@hality.com"
    await client.post(REGISTER_URL, json=_cadastro(email))

    respostas = [await client.post(RESEND_URL, json={"email": email}) for _ in range(7)]

    assert all(resposta.status_code == 202 for resposta in respostas)
    assert len(await _acoes_de_verificacao(db_session, email)) == 1 + 5


@pytest.mark.asyncio
async def test_refresh_de_conta_nao_verificada_retorna_401_e_limpa_cookie(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "refresh-pendente@hality.com"
    await client.post(REGISTER_URL, json=_cadastro(email))
    await client.post(CONFIRM_URL, json={"token": await _token_ativo(db_session, email)})
    await _login(client, email)
    await db_session.execute(update(User).where(User.email == email).values(is_verified=False))
    await db_session.commit()

    resposta = await client.post(REFRESH_URL)

    assert resposta.status_code == 401
    assert 'refresh_token=""' in resposta.headers.get("set-cookie", "")
    assert await db_session.scalar(select(RefreshToken)) is None


@pytest.mark.asyncio
async def test_fluxo_nao_registra_token_senha_ou_email_nos_logs(
    client: AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    email = "logs@hality.com"
    caplog.set_level(logging.DEBUG, logger="app")
    caplog.set_level(logging.INFO)

    await client.post(REGISTER_URL, json=_cadastro(email))
    await client.post(RESEND_URL, json={"email": email})
    token = await _token_ativo(db_session, email)
    await _login(client, email)
    await client.post(CONFIRM_URL, json={"token": token})

    assert token not in caplog.text
    assert SENHA not in caplog.text
    assert email not in caplog.text


@pytest.mark.asyncio
async def test_outbox_entrega_link_de_confirmacao(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "entrega@hality.com"
    await client.post(REGISTER_URL, json=_cadastro(email))
    token = await _token_ativo(db_session, email)
    enviados = []

    class Provider:
        async def send(self, message) -> None:
            enviados.append(message)

    entregues = await dispatch_pending_emails(db_session, Provider())

    assert entregues == 1
    assert enviados[0].purpose == EMAIL_VERIFICATION
    assert enviados[0].recipient == email
    assert "purpose=email_verification" in enviados[0].token_url
    assert f"token={token}" in enviados[0].token_url
