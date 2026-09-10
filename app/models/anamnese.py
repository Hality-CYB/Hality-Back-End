"""Anamnese clínica preenchida pelo paciente."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Anamnese(Base):
    """Tabela `anamneses`.

    `respostas` guarda a lista de `RespostaItem` (schemas/anamnese.py) como
    veio no payload, preservando `enunciado` e `tipo` junto do `valor`.
    """

    __tablename__ = "anamneses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    data_preenchimento: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    versao_questionario: Mapped[str] = mapped_column(String(50))
    respostas: Mapped[list[dict]] = mapped_column(JSONB)
