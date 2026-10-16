"""Termos de consentimento vigentes (US-020) — público, para a tela de cadastro."""

from fastapi import APIRouter

from app.schemas.consentimento import TermosResponse
from app.services import consentimento_service

router = APIRouter(prefix="/consentimentos", tags=["consentimentos"])


@router.get("/termos", response_model=TermosResponse)
async def listar_termos() -> TermosResponse:
    """Texto e versão vigentes de cada finalidade. Nenhuma está marcada por padrão."""
    return consentimento_service.listar_termos()
