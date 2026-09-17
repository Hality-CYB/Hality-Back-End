from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.home import HomeResponse
from app.services import home_service

router = APIRouter(tags=["home"])


@router.get("/home", response_model=HomeResponse)
async def obter_home(usuario: CurrentUser, db: DbSession) -> HomeResponse:
    return await home_service.montar_home(db, usuario)
