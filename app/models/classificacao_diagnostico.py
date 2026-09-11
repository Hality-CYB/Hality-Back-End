"""Tabela de referência (lookup) das classificações possíveis de diagnóstico."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ClassificacaoDiagnostico(Base):
    """Tabela `classificacoes_diagnostico`.

    `codigo` é o valor estável usado pela aplicação (ex: 'saudavel',
    'mau_halito', 'halitose_social'); `nome_exibicao` é o label amigável
    mostrado na UI; `ordem` é a ordem de severidade usada para ordenar na UI.
    """

    __tablename__ = "classificacoes_diagnostico"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    nome_exibicao: Mapped[str] = mapped_column(String(100))
    ordem: Mapped[int] = mapped_column()
