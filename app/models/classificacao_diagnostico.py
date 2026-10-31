"""Tabela de referência (lookup) das classificações possíveis de diagnóstico."""

from sqlalchemy import CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ClassificacaoDiagnostico(Base):
    """Tabela `classificacoes_diagnostico`.

    `codigo` é o valor estável usado pela aplicação (ex: 'halito_normal',
    'halitose_intima', 'mau_halito_social'); `nome_exibicao` é o label amigável
    mostrado na UI; `ordem` é o nível de severidade (1 a 3), único por
    classificação.
    """

    __tablename__ = "classificacoes_diagnostico"
    __table_args__ = (
        UniqueConstraint("ordem", name="uq_classificacoes_diagnostico_ordem"),
        CheckConstraint("ordem BETWEEN 1 AND 3", name="ck_classificacoes_diagnostico_ordem"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    nome_exibicao: Mapped[str] = mapped_column(String(100))
    ordem: Mapped[int] = mapped_column()
