"""Tentativa de login OAuth (state/PKCE/nonce) e o código de troca de uso único."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ESTADO_INICIADO = "iniciado"
ESTADO_EM_CALLBACK = "em_callback"
ESTADO_AUTENTICADO = "autenticado"
ESTADO_CONCLUIDO = "concluido"
ESTADO_FALHOU = "falhou"


class OAuthFluxo(Base):
    """Tabela `oauth_fluxos`: uma linha por clique em "entrar com Google".

    Ciclo: `iniciado` (authorize) -> `em_callback` (callback reivindicado, uma
    única vez) -> `autenticado` (código de troca emitido) -> `concluido`
    (código consumido), ou `falhou` em qualquer ponto. As transições são
    UPDATEs condicionais, então callback e troca repetidos/concorrentes não
    passam duas vezes.

    O `state` e o código de troca só existem aqui como hash SHA-256. O
    `code_verifier` e o `nonce` ficam em claro por poucos minutos (precisam ser
    reenviados/conferidos). `email`/`nome` só são guardados para um cadastro
    novo ainda pendente de consentimento e são apagados ao concluir. Nenhum
    token do Google é persistido.
    """

    __tablename__ = "oauth_fluxos"
    __table_args__ = (Index("ix_oauth_fluxos_criado_em", "criado_em"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(20))
    estado: Mapped[str] = mapped_column(String(20), default=ESTADO_INICIADO)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    nonce: Mapped[str] = mapped_column(String(64))
    code_verifier: Mapped[str] = mapped_column(String(128))
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    codigo_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    codigo_expira_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    nome: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    motivo_falha: Mapped[str | None] = mapped_column(String(50), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
