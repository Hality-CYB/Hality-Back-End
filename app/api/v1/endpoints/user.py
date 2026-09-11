from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.user import UserRead
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserRead])
async def list_users(db: DbSession) -> list[UserRead]:
    return await user_service.listar_usuarios(db)
