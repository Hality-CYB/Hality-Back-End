"""Acesso a dados da anamnese via repository - devolve `AnamneseRecord`
(DTO simples), nunca o objeto ORM, pra não vazar SQLAlchemy pro service."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.anamnese import Anamnese
from app.schemas.anamnese import ItemRespostaRegistrada


@dataclass
class AnamneseRecord:
    id_resp: int
    paciente_id: uuid.UUID
    data_preenchimento: datetime
    id_versao_questionario: str
    respostas: list[ItemRespostaRegistrada]


def _para_record(orm: Anamnese) -> AnamneseRecord:
    return AnamneseRecord(
        id_resp=orm.id,
        paciente_id=orm.paciente_id,
        data_preenchimento=orm.data_preenchimento,
        id_versao_questionario=orm.id_versao_questionario,
        respostas=[ItemRespostaRegistrada.model_validate(r) for r in orm.respostas],
    )


def _para_json(respostas: list[ItemRespostaRegistrada]) -> list[dict]:
    return [resposta.model_dump(mode="json") for resposta in respostas]


class AnamneseRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def salvar(
        self,
        paciente_id: uuid.UUID,
        id_versao_questionario: str,
        respostas: list[ItemRespostaRegistrada],
    ) -> AnamneseRecord:
        orm = Anamnese(
            paciente_id=paciente_id,
            id_versao_questionario=id_versao_questionario,
            respostas=_para_json(respostas),
        )
        self.db.add(orm)
        await self.db.commit()
        await self.db.refresh(orm)
        return _para_record(orm)

    async def listar_por_paciente(self, paciente_id: uuid.UUID) -> list[AnamneseRecord]:
        resultado = await self.db.execute(
            select(Anamnese)
            .where(Anamnese.paciente_id == paciente_id)
            .order_by(Anamnese.data_preenchimento.desc())
        )
        return [_para_record(orm) for orm in resultado.scalars().all()]

    async def obter_por_id(self, id_resp: int) -> AnamneseRecord | None:
        orm = await self.db.get(Anamnese, id_resp)
        return _para_record(orm) if orm is not None else None

    async def atualizar(
        self,
        id_resp: int,
        id_versao_questionario: str,
        respostas: list[ItemRespostaRegistrada],
    ) -> AnamneseRecord | None:
        orm = await self.db.get(Anamnese, id_resp)
        if orm is None:
            return None
        orm.id_versao_questionario = id_versao_questionario
        orm.respostas = _para_json(respostas)
        await self.db.commit()
        await self.db.refresh(orm)
        return _para_record(orm)

    async def deletar(self, id_resp: int) -> None:
        orm = await self.db.get(Anamnese, id_resp)
        if orm is not None:
            await self.db.delete(orm)
            await self.db.commit()


DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_anamnese_repository(db: DbSession) -> AnamneseRepository:
    return AnamneseRepository(db)
