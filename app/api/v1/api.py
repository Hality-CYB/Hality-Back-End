from fastapi import APIRouter

from app.api.v1.endpoints import (
    anamnese,
    diagnostico,
    health,
)


api_router = APIRouter()

api_router.include_router(
    health.router
)

api_router.include_router(
    anamnese.router
)

api_router.include_router(
    diagnostico.router
)