"""Consultas do login OAuth: fluxos (state/código de troca) e identidades externas."""

import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identidade_externa import IdentidadeExterna
from app.models.oauth_fluxo import (
    ESTADO_AUTENTICADO,
    ESTADO_CONCLUIDO,
    ESTADO_EM_CALLBACK,
    ESTADO_INICIADO,
    OAuthFluxo,
)


async def criar_fluxo(db: AsyncSession, **campos: object) -> OAuthFluxo:
    fluxo = OAuthFluxo(**campos)
    db.add(fluxo)
    await db.flush()
    return fluxo


async def purgar_fluxos_antigos(db: AsyncSession, *, antes_de: datetime) -> None:
    await db.execute(delete(OAuthFluxo).where(OAuthFluxo.criado_em < antes_de))


async def reivindicar_callback(
    db: AsyncSession, *, state_hash: str, agora: datetime
) -> OAuthFluxo | None:
    """Marca o fluxo como "em callback" uma única vez (UPDATE condicional).

    Devolve `None` se o state é desconhecido, expirou ou já foi usado — inclusive
    por uma requisição concorrente que chegou antes.
    """
    resultado = await db.execute(
        update(OAuthFluxo)
        .where(
            OAuthFluxo.state_hash == state_hash,
            OAuthFluxo.estado == ESTADO_INICIADO,
            OAuthFluxo.expira_em > agora,
        )
        .values(estado=ESTADO_EM_CALLBACK)
        .execution_options(synchronize_session=False)
    )
    if resultado.rowcount != 1:
        return None
    return await db.scalar(
        select(OAuthFluxo)
        .where(OAuthFluxo.state_hash == state_hash)
        .execution_options(populate_existing=True)
    )


async def buscar_fluxo_para_troca(
    db: AsyncSession, *, codigo_hash: str, agora: datetime
) -> OAuthFluxo | None:
    return await db.scalar(
        select(OAuthFluxo).where(
            OAuthFluxo.codigo_hash == codigo_hash,
            OAuthFluxo.estado == ESTADO_AUTENTICADO,
            OAuthFluxo.codigo_expira_em > agora,
        )
    )


async def consumir_codigo_de_troca(db: AsyncSession, *, fluxo_id: uuid.UUID) -> bool:
    """Gasta o código de troca uma única vez; `False` se alguém já o gastou."""
    resultado = await db.execute(
        update(OAuthFluxo)
        .where(OAuthFluxo.id == fluxo_id, OAuthFluxo.estado == ESTADO_AUTENTICADO)
        .values(estado=ESTADO_CONCLUIDO)
        .execution_options(synchronize_session=False)
    )
    return resultado.rowcount == 1


async def buscar_identidade(
    db: AsyncSession, *, provider: str, subject: str
) -> IdentidadeExterna | None:
    return await db.scalar(
        select(IdentidadeExterna).where(
            IdentidadeExterna.provider == provider, IdentidadeExterna.subject == subject
        )
    )


async def criar_identidade(
    db: AsyncSession, *, user_id: uuid.UUID, provider: str, subject: str
) -> IdentidadeExterna:
    identidade = IdentidadeExterna(user_id=user_id, provider=provider, subject=subject)
    db.add(identidade)
    await db.flush()
    return identidade
