"""Contrato HTTP do Resend e renderização dos emails transacionais."""

import json

import httpx
import pytest

from app.core.config import Settings
from app.services.identity_token_service import EmailMessage
from app.services.resend_email_provider import PermanentEmailError, ResendEmailProvider


def _settings(**overrides) -> Settings:
    data = {
        "postgres_host": "localhost",
        "postgres_port": 5432,
        "postgres_user": "hality",
        "postgres_password": "teste",
        "postgres_db": "hality",
        "secret_key": "teste",
        "email_provider": "resend",
        "resend_api_key": "re_teste",
        "resend_from_email": "CYB <onboarding@resend.dev>",
        "resend_test_recipient": "pessoa@example.com",
    }
    return Settings(**(data | overrides), _env_file=None)


@pytest.mark.asyncio
async def test_envia_convite_com_logos_link_e_idempotencia() -> None:
    requisicoes = []

    def receber(request: httpx.Request) -> httpx.Response:
        requisicoes.append(request)
        return httpx.Response(200, json={"id": "email_teste"})

    provider = ResendEmailProvider(_settings(), httpx.MockTransport(receber))
    await provider.send(
        EmailMessage(
            recipient="pessoa@example.com",
            purpose="invitation",
            token="segredo",
            token_url="http://localhost:3000?purpose=invitation&token=segredo",
            correlation_id="convite-unico",
        )
    )

    request = requisicoes[0]
    payload = json.loads(request.content)
    assert str(request.url) == "https://api.resend.com/emails"
    assert request.headers["Idempotency-Key"] == "convite-unico"
    assert payload["to"] == ["pessoa@example.com"]
    assert "token=segredo" in payload["text"]
    assert "&amp;token=segredo" in payload["html"]
    assert 'src="cid:cyb-logo"' in payload["html"]
    assert 'src="cid:hality-logo"' in payload["html"]
    assert {item["content_id"] for item in payload["attachments"]} == {
        "cyb-logo",
        "hality-logo",
    }


@pytest.mark.asyncio
async def test_review_escapa_texto_e_nao_inclui_observacao() -> None:
    payloads = []

    def receber(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "email_teste"})

    provider = ResendEmailProvider(_settings(), httpx.MockTransport(receber))
    await provider.send(
        EmailMessage(
            recipient="pessoa@example.com",
            purpose="diagnostic_review",
            token="",
            token_url="http://localhost:3000/paciente/diagnosticos/2",
            correlation_id="revisao-unica",
            review_result="Íntima <script>",
            professional_name="Dra. Ana & equipe",
            professional_specialty="Odontologia",
            professional_registration="CRO 123",
        )
    )
    assert "Íntima &lt;script&gt;" in payloads[0]["html"]
    assert "Dra. Ana &amp; equipe" in payloads[0]["html"]
    assert "CRO 123" in payloads[0]["text"]


@pytest.mark.asyncio
async def test_sandbox_rejeita_destinatario_diferente_sem_chamada_http() -> None:
    def nao_chamar(request: httpx.Request) -> httpx.Response:
        raise AssertionError("não deveria chamar o Resend")

    provider = ResendEmailProvider(_settings(), httpx.MockTransport(nao_chamar))
    with pytest.raises(PermanentEmailError):
        await provider.send(
            EmailMessage(
                recipient="outro@example.com",
                purpose="password_reset",
                token="segredo",
                token_url="http://localhost:3000?purpose=password_reset&token=segredo",
                correlation_id="reset-unico",
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["invitation", "password_reset", "diagnostic_review"])
async def test_dominio_verificado_envia_cada_fluxo_ao_destinatario_real(purpose: str) -> None:
    payloads = []

    def receber(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "email_teste"})

    provider = ResendEmailProvider(
        _settings(
            resend_from_email="CYB <notificacoes@example.com>",
            resend_test_recipient=None,
        ),
        httpx.MockTransport(receber),
    )
    await provider.send(
        EmailMessage(
            recipient="destinatario.real@example.com",
            purpose=purpose,
            token="segredo",
            token_url="https://app.example.com/acao",
            correlation_id=f"{purpose}-unico",
        )
    )

    assert payloads[0]["to"] == ["destinatario.real@example.com"]
