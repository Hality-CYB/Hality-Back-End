"""Serviço único para ações de identidade e entrega de seus e-mails."""

import base64
import hashlib
import hmac
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import quote

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.policies import tem_papel
from app.auth.users import password_helper
from app.core.config import get_settings
from app.models.identity_action import EmailOutbox, IdentityAction, IdentityRateLimit
from app.models.refresh_token import RefreshToken
from app.models.user import User

logger = logging.getLogger(__name__)

PASSWORD_RESET = "password_reset"
INVITATION = "invitation"
QUEUED = "queued"
SENT = "sent"
FAILED = "failed"
PROCESSING = "processing"
EXPIRED = "expired"
CONSUMED = "consumed"


class InvalidIdentityTokenError(Exception):
    """Token ausente, inválido, expirado, usado ou revogado."""


@dataclass(frozen=True)
class EmailMessage:
    recipient: str
    purpose: str
    token: str
    token_url: str
    correlation_id: str


class EmailProvider(Protocol):
    async def send(self, message: EmailMessage) -> None:
        """Entrega a mensagem ou levanta uma exceção transitória/permanente."""


class NoopEmailProvider:
    """Adapter padrão seguro para desenvolvimento; não faz chamada de rede."""

    async def send(self, message: EmailMessage) -> None:
        logger.info("identity email queued for delivery correlation_id=%s", message.correlation_id)


def get_email_provider() -> EmailProvider:
    """Resolve o adapter configurado; adapters reais podem ser registrados aqui."""
    if get_settings().email_provider.lower() == "noop":
        return NoopEmailProvider()
    raise RuntimeError("EMAIL_PROVIDER não suportado")


def _token_for(action_id: uuid.UUID, purpose: str) -> str:
    secret = get_settings().secret_key.get_secret_value().encode()
    payload = f"{purpose}:{action_id}".encode()
    digest = hmac.new(secret, payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def consume_recovery_rate_limit(db: AsyncSession, key: str) -> bool:
    """Registra a tentativa em banco e retorna se a janela foi excedida."""
    settings = get_settings()
    key_hash = _hash_token(key)
    now = _now()
    for _ in range(2):
        try:
            row = await db.scalar(
                select(IdentityRateLimit)
                .where(IdentityRateLimit.key_hash == key_hash)
                .with_for_update()
            )
            if row is None:
                db.add(
                    IdentityRateLimit(
                        key_hash=key_hash,
                        window_started_at=now,
                        attempts=1,
                    )
                )
                await db.commit()
                return False
            if (
                _utc(row.window_started_at)
                + timedelta(seconds=settings.identity_recovery_rate_window_seconds)
                <= now
            ):
                row.window_started_at = now
                row.attempts = 1
                await db.commit()
                return False
            if row.attempts >= settings.identity_recovery_rate_limit:
                return True
            row.attempts += 1
            await db.commit()
            return False
        except IntegrityError:
            await db.rollback()
    return True


async def _create_action(
    db: AsyncSession,
    user: User,
    purpose: str,
    *,
    commit: bool = True,
) -> str:
    now = _now()
    locked_user = await db.scalar(select(User).where(User.id == user.id).with_for_update())
    if locked_user is None:
        raise ValueError("usuário não encontrado")
    user = locked_user
    correlation_id = uuid.uuid4().hex
    action_id = uuid.uuid4()
    token = _token_for(action_id, purpose)

    old_action_ids = list(
        await db.scalars(
            select(IdentityAction.id).where(
                IdentityAction.user_id == user.id,
                IdentityAction.purpose == purpose,
                IdentityAction.used_at.is_(None),
                IdentityAction.revoked_at.is_(None),
            )
        )
    )
    if old_action_ids:
        await db.execute(
            update(IdentityAction)
            .where(IdentityAction.id.in_(old_action_ids))
            .values(revoked_at=now)
        )
        await db.execute(
            update(EmailOutbox)
            .where(
                EmailOutbox.action_id.in_(old_action_ids),
                EmailOutbox.status.in_((QUEUED, PROCESSING)),
            )
            .values(status=EXPIRED)
        )
    action = IdentityAction(
        id=action_id,
        user_id=user.id,
        purpose=purpose,
        token_hash=_hash_token(token),
        expires_at=now + timedelta(minutes=get_settings().identity_token_expire_minutes),
        correlation_id=correlation_id,
    )
    db.add(action)
    await db.flush()
    db.add(
        EmailOutbox(
            action_id=action_id,
            recipient_email=user.email,
            purpose=purpose,
            status=QUEUED,
            correlation_id=correlation_id,
        )
    )
    if commit:
        await db.commit()
    return correlation_id


async def request_password_recovery(db: AsyncSession, email: str) -> None:
    """Enfileira reset sem revelar se o e-mail existe."""
    user = await db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if user is not None and user.is_active:
        await _create_action(db, user, PASSWORD_RESET)


async def create_invitation(db: AsyncSession, user: User, *, commit: bool = True) -> str:
    """Cria uma ação de convite para um usuário já persistido."""
    user.is_active = False
    return await _create_action(db, user, INVITATION, commit=commit)


async def consume_identity_action(
    db: AsyncSession,
    token: str,
    new_password: str,
    purpose: str = PASSWORD_RESET,
    consentimentos: Sequence[object] | None = None,
    referencia_coleta: str | None = None,
) -> User:
    """Consome uma ação uma única vez e invalida refresh tokens do usuário."""
    action = await db.scalar(
        select(IdentityAction)
        .where(
            IdentityAction.token_hash == _hash_token(token),
            IdentityAction.purpose == purpose,
        )
        .with_for_update()
    )
    now = _now()
    if action is None or action.used_at is not None or action.revoked_at is not None:
        raise InvalidIdentityTokenError
    if _utc(action.expires_at) <= now:
        await db.execute(
            update(EmailOutbox)
            .where(EmailOutbox.action_id == action.id, EmailOutbox.status != CONSUMED)
            .values(status=EXPIRED)
        )
        await db.commit()
        raise InvalidIdentityTokenError

    user = await db.get(User, action.user_id)
    if user is None or (not user.is_active and purpose != INVITATION):
        raise InvalidIdentityTokenError

    action.used_at = now
    user.hashed_password = password_helper.hash(new_password)
    if purpose == INVITATION:
        user.is_active = True
        if consentimentos:
            from app.core.consentimentos import OrigemConsentimento
            from app.schemas.consentimento import DecisaoConsentimento
            from app.schemas.usuario import TipoUsuario
            from app.services import consentimento_service

            lista_decisoes = [
                d if isinstance(d, DecisaoConsentimento) else DecisaoConsentimento.model_validate(d)
                for d in consentimentos
            ]
            if tem_papel(user, TipoUsuario.PACIENTE):
                consentimento_service.validar_decisoes_cadastro(lista_decisoes)
            await consentimento_service.gravar_decisoes(
                db,
                titular=user,
                decisoes=lista_decisoes,
                origem=OrigemConsentimento.CONVITE,
                ator=user,
                referencia_coleta=referencia_coleta,
            )

    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
    await db.execute(
        update(EmailOutbox)
        .where(EmailOutbox.action_id == action.id, EmailOutbox.status != EXPIRED)
        .values(status=CONSUMED)
    )
    await db.commit()
    return user


async def consume_password_reset(db: AsyncSession, token: str, new_password: str) -> None:
    await consume_identity_action(db, token, new_password, PASSWORD_RESET)


async def consume_invitation(
    db: AsyncSession,
    token: str,
    new_password: str,
    consentimentos: Sequence[object] | None = None,
    referencia_coleta: str | None = None,
) -> User:
    return await consume_identity_action(
        db,
        token,
        new_password,
        INVITATION,
        consentimentos=consentimentos,
        referencia_coleta=referencia_coleta,
    )


async def dispatch_pending_emails(
    db: AsyncSession,
    provider: EmailProvider,
    limit: int = 50,
) -> int:
    """Entrega itens da outbox; falhas ficam disponíveis para retry."""
    now = _now()
    settings = get_settings()
    await db.execute(
        delete(IdentityRateLimit).where(
            IdentityRateLimit.window_started_at
            < now - timedelta(seconds=settings.identity_recovery_rate_window_seconds)
        )
    )
    await db.commit()
    rows: Sequence[EmailOutbox] = (
        await db.scalars(
            select(EmailOutbox)
            .where(
                EmailOutbox.status.in_((QUEUED, FAILED, PROCESSING)),
                EmailOutbox.available_at <= now,
            )
            .order_by(EmailOutbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for outbox in rows:
        outbox.status = PROCESSING
        outbox.available_at = now + timedelta(minutes=5)
    await db.commit()
    delivered = 0
    for outbox in rows:
        action = await db.get(IdentityAction, outbox.action_id)
        if action is None or action.used_at is not None:
            outbox.status = CONSUMED
            await db.commit()
            continue
        if action.revoked_at is not None or _utc(action.expires_at) <= now:
            outbox.status = EXPIRED
            await db.commit()
            continue
        outbox.attempts += 1
        try:
            token = _token_for(action.id, action.purpose)
            await provider.send(
                EmailMessage(
                    recipient=outbox.recipient_email,
                    purpose=outbox.purpose,
                    token=token,
                    token_url=(
                        f"{settings.identity_token_base_url.rstrip('/')}"
                        f"?purpose={quote(action.purpose)}&token={quote(token)}"
                    ),
                    correlation_id=outbox.correlation_id,
                )
            )
        except Exception as exc:  # noqa: BLE001
            outbox.status = FAILED
            outbox.failed_at = now
            outbox.available_at = now + timedelta(minutes=min(outbox.attempts, 60))
            outbox.last_error = type(exc).__name__[:255]
            await db.commit()
            continue
        outbox.status = SENT
        outbox.sent_at = now
        outbox.last_error = None
        await db.commit()
        delivered += 1
    return delivered
