"""Consultas do vínculo paciente-profissional (`pacientes_profissionais`)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.paciente_profissional import PacienteProfissional
from app.models.user import User


async def buscar_paciente_por_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email))


async def buscar_vinculo(db: AsyncSession, vinculo_id: int) -> PacienteProfissional | None:
    return await db.get(PacienteProfissional, vinculo_id)


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


VinculoDetalhado = tuple[PacienteProfissional, str, str]


async def situacao_vinculos_do_profissional(
    db: AsyncSession, profissional_id: uuid.UUID
) -> tuple[bool, bool]:
    """Retorna `(tem_algum_vinculo, tem_vinculo_ativo)`."""
    total, ativos = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(PacienteProfissional.ativo.is_(True)),
            ).where(PacienteProfissional.profissional_id == profissional_id)
        )
    ).one()
    return total > 0, ativos > 0


async def paciente_tem_vinculo_ativo(db: AsyncSession, paciente_id: uuid.UUID) -> bool:
    encontrado = await db.scalar(
        select(PacienteProfissional.id)
        .where(
            PacienteProfissional.paciente_id == paciente_id,
            PacienteProfissional.ativo.is_(True),
        )
        .limit(1)
    )
    return encontrado is not None


def _select_vinculo_detalhado():
    paciente = aliased(User)
    profissional = aliased(User)
    return (
        select(PacienteProfissional, paciente.name, profissional.name)
        .join(paciente, paciente.id == PacienteProfissional.paciente_id)
        .join(profissional, profissional.id == PacienteProfissional.profissional_id)
    )


async def buscar_vinculo_detalhado(db: AsyncSession, vinculo_id: int) -> VinculoDetalhado | None:
    resultado = await db.execute(
        _select_vinculo_detalhado().where(PacienteProfissional.id == vinculo_id)
    )
    linha = resultado.one_or_none()
    return None if linha is None else (linha[0], linha[1], linha[2])


async def listar_vinculos(
    db: AsyncSession,
    *,
    paciente_id: uuid.UUID | None,
    profissional_id: uuid.UUID | None,
    ativo: bool | None,
    offset: int,
    limite: int,
) -> tuple[list[VinculoDetalhado], int]:
    filtros: list[ColumnElement[bool]] = []
    if paciente_id is not None:
        filtros.append(PacienteProfissional.paciente_id == paciente_id)
    if profissional_id is not None:
        filtros.append(PacienteProfissional.profissional_id == profissional_id)
    if ativo is not None:
        filtros.append(PacienteProfissional.ativo.is_(ativo))

    total = await db.scalar(select(func.count()).select_from(PacienteProfissional).where(*filtros))
    resultado = await db.execute(
        _select_vinculo_detalhado()
        .where(*filtros)
        .order_by(PacienteProfissional.data_vinculo.desc(), PacienteProfissional.id.desc())
        .offset(offset)
        .limit(limite)
    )
    return list(resultado.tuples()), total or 0


def reativar_vinculo(vinculo: PacienteProfissional) -> None:
    vinculo.ativo = True
    vinculo.encerrado_em = None
