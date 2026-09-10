"""Persistência da anamnese em Postgres via SQLAlchemy async.

`AnamneseRepository` é o contrato que services/endpoints dependem — trocar a
implementação (como foi feito aqui, do mock em memória para
`SQLAlchemyAnamneseRepository`) não exige mudanças em service nem endpoint.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.anamnese import Anamnese
from app.schemas.anamnese import RespostaItem


@dataclass
class AnamneseRecord:
    id: int
    paciente_id: int
    data_preenchimento: datetime
    versao_questionario: str
    respostas: list[RespostaItem] = field(default_factory=list)


class AnamneseRepository(Protocol):
    async def salvar(
        self, paciente_id: int, versao_questionario: str, respostas: list[RespostaItem]
    ) -> AnamneseRecord: ...

    async def obter_por_id(self, anamnese_id: int) -> AnamneseRecord | None: ...

    async def listar_por_paciente(self, paciente_id: int) -> list[AnamneseRecord]: ...

    async def atualizar(
        self, anamnese_id: int, versao_questionario: str, respostas: list[RespostaItem]
    ) -> AnamneseRecord | None: ...

    async def deletar(self, anamnese_id: int) -> bool: ...


def _para_registro(anamnese: Anamnese) -> AnamneseRecord:
    return AnamneseRecord(
        id=anamnese.id,
        paciente_id=anamnese.paciente_id,
        data_preenchimento=anamnese.data_preenchimento,
        versao_questionario=anamnese.versao_questionario,
        respostas=[RespostaItem(**r) for r in anamnese.respostas],
    )


class SQLAlchemyAnamneseRepository:
    """Implementação real de `AnamneseRepository`, sobre a tabela `anamneses`."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def salvar(
        self, paciente_id: int, versao_questionario: str, respostas: list[RespostaItem]
    ) -> AnamneseRecord:
        anamnese = Anamnese(
            paciente_id=paciente_id,
            versao_questionario=versao_questionario,
            respostas=[r.model_dump(mode="json") for r in respostas],
        )
        self._db.add(anamnese)
        await self._db.commit()
        await self._db.refresh(anamnese)
        return _para_registro(anamnese)

    async def obter_por_id(self, anamnese_id: int) -> AnamneseRecord | None:
        anamnese = await self._db.get(Anamnese, anamnese_id)
        return _para_registro(anamnese) if anamnese is not None else None

    async def listar_por_paciente(self, paciente_id: int) -> list[AnamneseRecord]:
        resultado = await self._db.execute(
            select(Anamnese).where(Anamnese.paciente_id == paciente_id)
        )
        return [_para_registro(a) for a in resultado.scalars().all()]

    async def atualizar(
        self, anamnese_id: int, versao_questionario: str, respostas: list[RespostaItem]
    ) -> AnamneseRecord | None:
        anamnese = await self._db.get(Anamnese, anamnese_id)
        if anamnese is None:
            return None
        anamnese.versao_questionario = versao_questionario
        anamnese.respostas = [r.model_dump(mode="json") for r in respostas]
        await self._db.commit()
        await self._db.refresh(anamnese)
        return _para_registro(anamnese)

    async def deletar(self, anamnese_id: int) -> bool:
        anamnese = await self._db.get(Anamnese, anamnese_id)
        if anamnese is None:
            return False
        await self._db.delete(anamnese)
        await self._db.commit()
        return True


def get_anamnese_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AnamneseRepository:
    return SQLAlchemyAnamneseRepository(db)


AnamneseRepositoryDep = Annotated[AnamneseRepository, Depends(get_anamnese_repository)]
