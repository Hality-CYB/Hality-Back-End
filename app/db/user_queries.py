"""Consultas de usuários e dos dados de profissional (`users`, `profissionais`)."""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profissional import Profissional
from app.models.user import User
from app.schemas.usuario import TipoUsuario

UsuarioComProfissional = tuple[User, Profissional | None]


def _select_usuario_com_profissional():
    return select(User, Profissional).outerjoin(Profissional, Profissional.usuario_id == User.id)


async def email_em_uso(db: AsyncSession, email: str) -> bool:
    encontrado = await db.scalar(
        select(User.id).where(func.lower(User.email) == email.lower()).limit(1)
    )
    return encontrado is not None


async def buscar_usuario(db: AsyncSession, usuario_id: uuid.UUID) -> User | None:
    return await db.get(User, usuario_id)


async def bloquear_outros_admins_efetivos(
    db: AsyncSession, usuario_id: uuid.UUID
) -> list[uuid.UUID]:
    # O próprio usuário entra no FOR UPDATE (em ordem de id) para que duas
    # remoções de acesso simultâneas se serializem em vez de causar deadlock;
    # a segunda relê as linhas já sem o admin removido pela primeira.
    ids = await db.scalars(
        select(User.id)
        .where(
            User.is_active.is_(True),
            or_(User.role == TipoUsuario.ADMIN, User.is_superuser.is_(True)),
        )
        .order_by(User.id)
        .with_for_update()
    )
    return [admin_id for admin_id in ids if admin_id != usuario_id]


async def buscar_usuario_com_profissional(
    db: AsyncSession, usuario_id: uuid.UUID
) -> UsuarioComProfissional | None:
    resultado = await db.execute(_select_usuario_com_profissional().where(User.id == usuario_id))
    linha = resultado.one_or_none()
    return None if linha is None else (linha[0], linha[1])


def _filtros_listagem(
    role: str | None, ativo: bool | None, busca: str | None
) -> list[ColumnElement[bool]]:
    filtros: list[ColumnElement[bool]] = []
    if role is not None:
        filtros.append(User.role == role)
    if ativo is not None:
        filtros.append(User.is_active.is_(ativo))
    if busca:
        filtros.append(
            or_(
                User.name.icontains(busca, autoescape=True),
                User.email.icontains(busca, autoescape=True),
            )
        )
    return filtros


async def listar_usuarios(
    db: AsyncSession,
    *,
    role: str | None,
    ativo: bool | None,
    busca: str | None,
    offset: int,
    limite: int,
) -> tuple[list[UsuarioComProfissional], int]:
    filtros = _filtros_listagem(role, ativo, busca)

    total = await db.scalar(select(func.count()).select_from(User).where(*filtros))
    resultado = await db.execute(
        _select_usuario_com_profissional()
        .where(*filtros)
        .order_by(User.name, User.id)
        .offset(offset)
        .limit(limite)
    )
    return list(resultado.tuples()), total or 0


async def criar_usuario(db: AsyncSession, **campos: Any) -> User:
    usuario = User(**campos)
    db.add(usuario)
    await db.flush()
    return usuario


async def criar_profissional(
    db: AsyncSession, usuario_id: uuid.UUID, **campos: Any
) -> Profissional:
    profissional = Profissional(usuario_id=usuario_id, **campos)
    db.add(profissional)
    await db.flush()
    return profissional


async def remover_profissional(db: AsyncSession, profissional: Profissional) -> None:
    await db.delete(profissional)
    await db.flush()
