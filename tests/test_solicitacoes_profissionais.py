import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.auth.users import get_jwt_strategy, password_helper
from app.models import EmailOutbox, IdentityRateLimit, Profissional, SolicitacaoProfissional, User
from app.services.identity_token_service import dispatch_pending_emails
from app.services.resend_email_provider import _render

PUBLICO = "/api/v1/auth/profissionais/solicitacoes"
ADMIN = "/api/v1/admin/solicitacoes-profissionais"
DADOS = dict(
    nome="Profissional Teste",
    email="profissional@example.com",
    telefone="51999999999",
    registro_profissional="CRO-RS 12345",
    especialidade="Odontologia",
    aceita_termos=True,
)
SENHA = "SenhaSegura123!"


@pytest.mark.asyncio
async def test_worker_preserva_limite_da_solicitacao_durante_a_hora_inteira(client, db_session):
    await client.post(PUBLICO, json=DADOS)
    limite = await db_session.scalar(select(IdentityRateLimit))
    limite.window_started_at = datetime.now(UTC) - timedelta(minutes=30)
    limite.attempts = 6
    await db_session.commit()
    await dispatch_pending_emails(db_session, SimpleNamespace(send=AsyncMock()))
    assert (
        await client.post(PUBLICO, json={**DADOS, "email": "outro@example.com"})
    ).status_code == 429


async def cabecalho(db, role="admin"):
    user = User(
        id=uuid.uuid4(),
        email=f"{role}@example.com",
        name=role,
        role=role,
        hashed_password=password_helper.hash(SENHA),
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.commit()
    return {"Authorization": f"Bearer {await get_jwt_strategy().write_token(user)}"}


@pytest.mark.asyncio
async def test_solicitacao_nao_cria_conta_ou_acesso_e_preserva_dados(client, db_session):
    assert (await client.post(PUBLICO, json=DADOS)).status_code == 202
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0
    assert await db_session.scalar(select(func.count()).select_from(EmailOutbox)) == 0
    login = await client.post(
        "/api/v1/auth/login", data={"username": DADOS["email"], "password": SENHA}
    )
    assert login.status_code == 400
    duplicada = {**DADOS, "email": DADOS["email"].upper(), "nome": "Outro nome"}
    assert (await client.post(PUBLICO, json=duplicada)).status_code == 409
    s = await db_session.scalar(select(SolicitacaoProfissional))
    assert s.nome == DADOS["nome"] and s.status == "pendente" and s.termos_aceitos_em


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "campo,valor",
    [
        ("nome", " "),
        ("email", "invalido"),
        ("registro_profissional", " "),
        ("especialidade", " "),
        ("aceita_termos", False),
        ("role", "admin"),
        ("vinculado_hality", True),
    ],
)
async def test_valida_campos_e_impede_autoatribuicao_de_acesso(client, campo, valor):
    assert (await client.post(PUBLICO, json={**DADOS, campo: valor})).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("role,esperado", [(None, 401), ("paciente", 403), ("profissional", 403)])
async def test_apenas_admin_lista_e_decide(client, db_session, role, esperado):
    headers = await cabecalho(db_session, role) if role else {}
    assert (await client.get(ADMIN, headers=headers)).status_code == esperado
    assert (
        await client.post(
            f"{ADMIN}/{uuid.uuid4()}/decisao", json={"decisao": "aprovada"}, headers=headers
        )
    ).status_code == esperado


@pytest.mark.asyncio
async def test_aprovacao_convite_ativacao_e_nao_concede_vinculo_hality(client, db_session):
    headers = await cabecalho(db_session)
    await client.post(PUBLICO, json=DADOS)
    lista = (await client.get(ADMIN, headers=headers)).json()
    assert lista["total"] == 1
    id = lista["itens"][0]["id"]
    resposta = await client.post(
        f"{ADMIN}/{id}/decisao", json={"decisao": "aprovada"}, headers=headers
    )
    assert resposta.status_code == 200
    user = await db_session.get(User, uuid.UUID(resposta.json()["usuario_id"]))
    assert user.role == "profissional" and not user.is_active and not user.is_verified
    perfil = await db_session.get(Profissional, user.id)
    assert perfil.registro_profissional == DADOS["registro_profissional"]
    assert not perfil.vinculado_hality
    provider = SimpleNamespace(send=AsyncMock())
    assert await dispatch_pending_emails(db_session, provider) == 1
    mensagem = provider.send.call_args.args[0]
    assert mensagem.purpose == "professional_approved"
    assert "purpose=invitation" in mensagem.token_url
    assunto, html, texto = _render(mensagem, 360)
    assert "aprovado" in assunto
    assert "O link expira em 6 horas." in html
    assert "O link expira em 6 horas." in texto
    assert (
        await client.get(
            "/api/v1/profissional/resumo",
            headers={"Authorization": f"Bearer {await get_jwt_strategy().write_token(user)}"},
        )
    ).status_code == 401
    resposta = await client.post(
        "/api/v1/auth/invitation/confirm", json={"token": mensagem.token, "senha": SENHA}
    )
    assert resposta.status_code == 204
    login = await client.post(
        "/api/v1/auth/login", data={"username": user.email, "password": SENHA}
    )
    assert login.status_code == 200
    assert (
        await client.post(f"{ADMIN}/{id}/decisao", json={"decisao": "recusada"}, headers=headers)
    ).status_code == 409
    assert await db_session.scalar(select(func.count()).select_from(EmailOutbox)) == 1


@pytest.mark.asyncio
async def test_recusa_notifica_sem_criar_conta_com_retry_da_outbox(client, db_session):
    headers = await cabecalho(db_session)
    await client.post(PUBLICO, json=DADOS)
    id = (await client.get(ADMIN, headers=headers)).json()["itens"][0]["id"]
    assert (
        await client.post(f"{ADMIN}/{id}/decisao", json={"decisao": "recusada"}, headers=headers)
    ).status_code == 200
    provider = SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("temporário")))
    assert await dispatch_pending_emails(db_session, provider) == 0
    email = await db_session.scalar(select(EmailOutbox))
    assert email.status == "failed"
    email.available_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    provider.send = AsyncMock()
    assert await dispatch_pending_emails(db_session, provider) == 1
    mensagem = provider.send.call_args.args[0]
    assert mensagem.purpose == "professional_rejected" and not mensagem.token
    assert "não aprovada" in _render(mensagem, 60)[1]
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
    assert (await client.get(f"{ADMIN}?status=recusada", headers=headers)).json()["total"] == 1


@pytest.mark.asyncio
async def test_conta_criada_entre_solicitacao_e_aprovacao_nao_e_convertida(client, db_session):
    headers = await cabecalho(db_session)
    await client.post(PUBLICO, json=DADOS)
    id = (await client.get(ADMIN, headers=headers)).json()["itens"][0]["id"]
    paciente = User(email=DADOS["email"], name="Paciente", role="paciente", hashed_password="hash")
    db_session.add(paciente)
    await db_session.commit()
    assert (
        await client.post(f"{ADMIN}/{id}/decisao", json={"decisao": "aprovada"}, headers=headers)
    ).status_code == 409
    await db_session.refresh(paciente)
    assert paciente.role == "paciente"
    assert (await client.post(PUBLICO, json=DADOS)).status_code == 409


@pytest.mark.asyncio
async def test_limite_de_solicitacoes_e_paginacao(client, db_session):
    headers = await cabecalho(db_session)
    for n in range(6):
        assert (
            await client.post(PUBLICO, json={**DADOS, "email": f"prof{n}@example.com"})
        ).status_code == 202
    assert (
        await client.post(PUBLICO, json={**DADOS, "email": "extra@example.com"})
    ).status_code == 429
    lista = (await client.get(f"{ADMIN}?limite=2&pagina=2", headers=headers)).json()
    assert lista["total"] == 6 and lista["total_paginas"] == 3 and len(lista["itens"]) == 2
    assert (await client.get(f"{ADMIN}?limite=10000", headers=headers)).status_code == 422
