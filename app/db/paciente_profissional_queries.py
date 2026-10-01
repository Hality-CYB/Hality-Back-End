"""Consultas do vínculo paciente-profissional (`pacientes_profissionais`)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paciente_profissional import PacienteProfissional
from app.models.user import User


async def buscar_paciente_por_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email))


async def buscar_vinculo_ativo(
    db: AsyncSession,
    paciente_id: uuid.UUID,
    profissional_id: uuid.UUID,
) -> PacienteProfissional | None:
    return await db.scalar(
        select(PacienteProfissional).where(
            PacienteProfissional.paciente_id == paciente_id,
            PacienteProfissional.profissional_id == profissional_id,
            PacienteProfissional.ativo.is_(True),
        )
    )


async def profissional_tem_acesso(
    db: AsyncSession,
    paciente_id: uuid.UUID,
    profissional_id: uuid.UUID,
) -> bool:
    """True se existe vínculo **ativo** entre o profissional e o paciente."""
    return await buscar_vinculo_ativo(db, paciente_id, profissional_id) is not None


async def paciente_tem_vinculo_ativo(
    db: AsyncSession,
    paciente_id: uuid.UUID,
) -> bool:
    """True se o paciente tem vínculo **ativo** com algum profissional."""
    result = await db.execute(
        select(PacienteProfissional.id)
        .where(
            PacienteProfissional.paciente_id == paciente_id,
            PacienteProfissional.ativo.is_(True),
        )
        .limit(1)
    )

    return result.scalar_one_or_none() is not None


async def criar_vinculo(
    db: AsyncSession,
    paciente_id: uuid.UUID,
    profissional_id: uuid.UUID,
) -> PacienteProfissional:
    vinculo = PacienteProfissional(paciente_id=paciente_id, profissional_id=profissional_id)
    db.add(vinculo)
    await db.flush()
    return vinculo


def encerrar_vinculo(vinculo: PacienteProfissional) -> None:
    vinculo.ativo = False
    vinculo.encerrado_em = datetime.now(UTC)


async def listar_vinculos_ativos(
    db: AsyncSession,
    profissional_id: uuid.UUID,
) -> list[tuple[PacienteProfissional, User]]:
    resultado = await db.execute(
        select(PacienteProfissional, User)
        .join(User, User.id == PacienteProfissional.paciente_id)
        .where(
            PacienteProfissional.profissional_id == profissional_id,
            PacienteProfissional.ativo.is_(True),
        )
        .order_by(User.name)
    )
    return list(resultado.all())
