"""Conteúdo educativo (dica ou protocolo) associado a uma classificação de diagnóstico."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConteudoDiagnostico(Base):
    """Tabela `conteudos_diagnostico`.

    `classificacao_id` é nulo quando o conteúdo é genérico, não ligado a uma
    classificação específica. O formato de `dados` depende de `tipo` (dica ou
    protocolo) e é resolvido em tempo de execução pela aplicação.
    """

    __tablename__ = "conteudos_diagnostico"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    classificacao_id: Mapped[int | None] = mapped_column(
        ForeignKey("classificacoes_diagnostico.id"), nullable=True
    )
    tipo: Mapped[str] = mapped_column(String(20))
    titulo: Mapped[str] = mapped_column(String(255))
    dados: Mapped[dict] = mapped_column(JSONB)
