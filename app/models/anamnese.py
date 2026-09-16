"""Anamnese clínica preenchida pelo paciente."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Anamnese(Base):
    """Tabela `anamneses`.

    `respostas` guarda a lista de `ItemRespostaRegistrada` (schemas/anamnese.py),
    já validada e tipada pelo lexer (anamnese_lexer.py) - preserva `des_pergunta`/
    `des_resposta` (texto, pra auditoria) junto de `valor`/`tipo_resposta` (forma
    tipada). `id_versao_questionario` referencia a versão do questionário
    (app/models/questionario.py) usada no preenchimento.
    """

    __tablename__ = "anamneses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paciente_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    data_preenchimento: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    id_versao_questionario: Mapped[str] = mapped_column(String(50), nullable=False)
    respostas: Mapped[list[dict]] = mapped_column(JSONB)
