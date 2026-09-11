from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def listar(db: AsyncSession) -> list[User]:
    resultado = await db.execute(select(User).order_by(User.id))
    return list(resultado.scalars().all())
