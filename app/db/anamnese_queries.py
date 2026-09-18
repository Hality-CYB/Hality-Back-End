"""Acesso a dados da anamnese — só SQL, nenhuma regra de negócio.

Consumido por app/services/anamnese_service.py, que decide o que fazer com
o resultado (validar, formatar resposta, levantar erro de negócio). Esse
módulo não sabe o que é "obrigatório" nem o que é HTTP 404 — só lê e escreve
na tabela `anamneses`.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.anamnese import Anamnese


async def inserir(db: AsyncSession, paciente_id: uuid.UUID, respostas: list[dict]) -> Anamnese:
    anamnese = Anamnese(paciente_id=paciente_id, respostas=respostas)
    db.add(anamnese)
    await db.commit()
    await db.refresh(anamnese)
    return anamnese


async def buscar_por_id(db: AsyncSession, anamnese_id: int) -> Anamnese | None:
    return await db.get(Anamnese, anamnese_id)


async def listar_por_paciente(db: AsyncSession, paciente_id: uuid.UUID) -> list[Anamnese]:
    resultado = await db.execute(
        select(Anamnese)
        .where(Anamnese.paciente_id == paciente_id)
        .order_by(Anamnese.data_preenchimento.desc())
    )
    return list(resultado.scalars().all())


async def atualizar(db: AsyncSession, anamnese: Anamnese, respostas: list[dict]) -> Anamnese:
    anamnese.respostas = respostas
    await db.commit()
    await db.refresh(anamnese)
    return anamnese


async def deletar(db: AsyncSession, anamnese: Anamnese) -> None:
    await db.delete(anamnese)
    await db.commit()
