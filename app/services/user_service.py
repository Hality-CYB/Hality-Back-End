from sqlalchemy.ext.asyncio import AsyncSession

from app.db import user_queries
from app.schemas.user import UserRead


async def listar_usuarios(db: AsyncSession) -> list[UserRead]:
    usuarios = await user_queries.listar(db)
    return [UserRead.model_validate(u) for u in usuarios]
