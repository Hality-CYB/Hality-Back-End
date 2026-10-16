"""Consultas da trilha de consentimentos (`consentimento_eventos`). Só insere e lê."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consentimento import ConsentimentoEvento


async def inserir_evento(db: AsyncSession, **campos: Any) -> ConsentimentoEvento:
    evento = ConsentimentoEvento(**campos)
    db.add(evento)
    await db.flush()
    return evento


async def ultimos_eventos(
    db: AsyncSession, titular_id: uuid.UUID
) -> dict[str, ConsentimentoEvento]:
    """Evento mais recente de cada finalidade do titular, indexado pela finalidade."""
    mais_recentes = (
        select(func.max(ConsentimentoEvento.id))
        .where(ConsentimentoEvento.titular_id == titular_id)
        .group_by(ConsentimentoEvento.finalidade)
    )
    eventos = await db.scalars(
        select(ConsentimentoEvento).where(ConsentimentoEvento.id.in_(mais_recentes))
    )
    return {evento.finalidade: evento for evento in eventos}
