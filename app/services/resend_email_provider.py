"""Entrega transacional da outbox pelo Resend."""

import base64
from functools import lru_cache
from html import escape
from pathlib import Path

import httpx

from app.core.config import Settings, get_settings
from app.services.identity_token_service import (
    DIAGNOSTIC_REVIEW,
    INVITATION,
    PASSWORD_RESET,
    EmailMessage,
)

RESEND_URL = "https://api.resend.com/emails"


class PermanentEmailError(Exception):
    """Erro de configuração ou destinatário que não deve consumir novos retries."""


class SandboxRecipientError(PermanentEmailError):
    """Destinatário aguarda a troca do remetente de testes por um domínio verificado."""


@lru_cache(maxsize=1)
def _logos() -> tuple[str, str]:
    assets = Path(__file__).resolve().parents[1] / "assets"
    return tuple(
        base64.b64encode((assets / nome).read_bytes()).decode("ascii")
        for nome in ("cyb-logo.png", "hality-logo.png")
    )


@lru_cache(maxsize=1)
def _email_html() -> str:
    return (Path(__file__).resolve().parents[1] / "assets" / "email.html").read_text(
        encoding="utf-8"
    )


def _render(message: EmailMessage, token_expiry_minutes: int) -> tuple[str, str, str]:
    if message.purpose == INVITATION:
        subject = "Seu convite para o Check Your Breath"
        title = "Você foi convidado(a)"
        description = (
            "A equipe Hality convidou você para acessar o Check Your Breath. "
            "Defina sua senha para ativar a conta."
        )
        button = "Aceitar convite"
        detail = (
            f"O link expira em {token_expiry_minutes} minutos. "
            "Se não esperava este convite, ignore a mensagem."
        )
    elif message.purpose == PASSWORD_RESET:
        subject = "Redefina sua senha do Check Your Breath"
        title = "Redefinição de senha"
        description = (
            "Recebemos uma solicitação para redefinir sua senha. "
            "Use o link abaixo para escolher uma nova senha."
        )
        button = "Redefinir senha"
        detail = (
            f"O link expira em {token_expiry_minutes} minutos. "
            "Se não fez a solicitação, ignore a mensagem."
        )
    elif message.purpose == DIAGNOSTIC_REVIEW:
        subject = "Sua análise foi revisada no Check Your Breath"
        title = "Sua análise foi revisada"
        description = "Um profissional revisou o resultado da sua análise no Check Your Breath."
        button = "Ver análise completa"
        profissional = message.professional_name or "Profissional Hality"
        info = [profissional]
        if message.professional_specialty:
            info.append(message.professional_specialty)
        if message.professional_registration:
            info.append(f"Registro: {message.professional_registration}")
        detail = (
            f"Classificação revisada: {message.review_result or 'Disponível na plataforma'}. "
            f"Profissional responsável: {', '.join(info)}. "
            "Consulte os detalhes na plataforma."
        )
    else:
        raise PermanentEmailError("finalidade de email desconhecida")

    text = (
        f"{title}\n\n{description}\n\n{detail}\n\n"
        f"{button}: {message.token_url}\n\nEquipe Hality | Check Your Breath"
    )
    safe_url = escape(message.token_url, quote=True)
    html = _email_html().format(
        title=escape(title),
        description=escape(description),
        detail=escape(detail),
        url=safe_url,
        button=escape(button),
    )
    return subject, html, text


class ResendEmailProvider:
    def __init__(
        self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None
    ):
        self.settings = settings or get_settings()
        self.transport = transport

    async def send(self, message: EmailMessage) -> None:
        allowed = self.settings.resend_test_recipient
        if allowed and message.recipient.casefold() != allowed.casefold():
            raise SandboxRecipientError("destinatário fora da lista de testes")
        subject, html, plain = _render(message, self.settings.identity_token_expire_minutes)
        cyb_logo, hality_logo = _logos()
        payload = {
            "from": self.settings.resend_from_email,
            "to": [message.recipient],
            "subject": subject,
            "html": html,
            "text": plain,
            "attachments": [
                {
                    "filename": "cyb-logo.png",
                    "content": cyb_logo,
                    "content_id": "cyb-logo",
                    "content_type": "image/png",
                },
                {
                    "filename": "hality-logo.png",
                    "content": hality_logo,
                    "content_id": "hality-logo",
                    "content_type": "image/png",
                },
            ],
        }
        async with httpx.AsyncClient(timeout=15, transport=self.transport) as client:
            response = await client.post(
                RESEND_URL,
                headers={
                    "Authorization": f"Bearer {self.settings.resend_api_key.get_secret_value()}",
                    "Idempotency-Key": message.correlation_id,
                },
                json=payload,
            )
        if response.status_code in {400, 401, 403, 422}:
            raise PermanentEmailError(f"Resend rejeitou o envio (HTTP {response.status_code})")
        response.raise_for_status()
        if not response.json().get("id"):
            raise RuntimeError("Resend não confirmou o identificador do email")
