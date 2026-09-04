"""Persistência simulada da anamnese.

A issue #18 pede explicitamente um "mock disponível para o FE antes da
implementação real". O banco de verdade (Postgres + SQLAlchemy async +
Alembic) será modelado e implementado por outra pessoa/issue, seguindo o
formato de tabela citado na issue: anamneses(id, paciente_id,
data_preenchimento, respostas jsonb).

`AnamneseRepository` é o contrato que essa implementação real deve seguir.
Trocar `InMemoryAnamneseRepository` por uma versão com SQLAlchemy é a única
mudança necessária — services e endpoints não sabem (nem devem saber) que a
persistência é em memória.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Protocol

from fastapi import Depends

from app.schemas.anamnese import RespostaItem


@dataclass
class AnamneseRecord:
    id: int
    paciente_id: int
    data_preenchimento: datetime
    versao_questionario: str
    respostas: list[RespostaItem] = field(default_factory=list)


class AnamneseRepository(Protocol):
    def salvar(
        self, paciente_id: int, versao_questionario: str, respostas: list[RespostaItem]
    ) -> AnamneseRecord: ...

    def obter_por_id(self, anamnese_id: int) -> AnamneseRecord | None: ...

    def listar_por_paciente(self, paciente_id: int) -> list[AnamneseRecord]: ...

    def atualizar(
        self, anamnese_id: int, versao_questionario: str, respostas: list[RespostaItem]
    ) -> AnamneseRecord | None: ...

    def deletar(self, anamnese_id: int) -> bool: ...


class InMemoryAnamneseRepository:
    """Implementação temporária, em memória (dict). Não é thread-safe nem
    persiste entre reinicializações do processo — serve só como mock até o
    banco real ser implementado."""

    def __init__(self) -> None:
        self._registros: dict[int, AnamneseRecord] = {}
        self._proximo_id = 1

    def salvar(
        self, paciente_id: int, versao_questionario: str, respostas: list[RespostaItem]
    ) -> AnamneseRecord:
        registro = AnamneseRecord(
            id=self._proximo_id,
            paciente_id=paciente_id,
            data_preenchimento=datetime.now(UTC),
            versao_questionario=versao_questionario,
            respostas=respostas,
        )
        self._registros[registro.id] = registro
        self._proximo_id += 1
        return registro

    def obter_por_id(self, anamnese_id: int) -> AnamneseRecord | None:
        return self._registros.get(anamnese_id)

    def listar_por_paciente(self, paciente_id: int) -> list[AnamneseRecord]:
        return [r for r in self._registros.values() if r.paciente_id == paciente_id]

    def atualizar(
        self, anamnese_id: int, versao_questionario: str, respostas: list[RespostaItem]
    ) -> AnamneseRecord | None:
        registro = self._registros.get(anamnese_id)
        if registro is None:
            return None
        registro.versao_questionario = versao_questionario
        registro.respostas = respostas
        return registro

    def deletar(self, anamnese_id: int) -> bool:
        return self._registros.pop(anamnese_id, None) is not None


# Singleton do processo — igual a um "banco" único compartilhado pelas
# requisições enquanto o repositório for o mock em memória.
_repositorio = InMemoryAnamneseRepository()


def get_anamnese_repository() -> AnamneseRepository:
    return _repositorio


AnamneseRepositoryDep = Annotated[AnamneseRepository, Depends(get_anamnese_repository)]
