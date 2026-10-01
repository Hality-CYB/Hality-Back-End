"""Vínculo opcional entre paciente e profissional."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PacienteProfissional(Base):
    """Tabela `pacientes_profissionais`.

    Desvincular não apaga a linha: marca `ativo=False` e preenche
    `encerrado_em`, preservando o histórico do vínculo para auditoria. Um
    índice único parcial (só sobre linhas com `ativo=True`) garante no banco
    que não existam dois vínculos ativos para o mesmo par paciente/profissional,
    mas permite revincular depois de uma desvinculação (nova linha).
    """

    __tablename__ = "pacientes_profissionais"
    # Criado na migration 198bcce46c43; declarado aqui para o autogenerate não
    # propor removê-lo.
    __table_args__ = (
        Index(
            "ix_pacientes_profissionais_par_ativo",
            "paciente_id",
            "profissional_id",
            unique=True,
            postgresql_where=text("ativo"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paciente_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    profissional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profissionais.usuario_id", ondelete="CASCADE")
    )
    data_vinculo: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    ativo: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
    )
    encerrado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
