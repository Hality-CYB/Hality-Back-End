from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentAdminMutationDep, DbSession
from app.schemas.rotulo_dataset import RotuloDatasetCreate, RotuloDatasetItem
from app.services import rotulo_dataset_service

router = APIRouter(prefix="/admin/diagnosticos", tags=["admin-rotulos-dataset"])


@router.post(
    "/{diagnostico_id}/rotulos-dataset",
    response_model=RotuloDatasetItem,
    status_code=status.HTTP_201_CREATED,
)
async def criar_rotulo_dataset(
    diagnostico_id: int,
    payload: RotuloDatasetCreate,
    admin: CurrentAdminMutationDep,
    db: DbSession,
) -> RotuloDatasetItem:
    try:
        return await rotulo_dataset_service.criar(
            db,
            diagnostico_id,
            payload.classificacao,
            payload.version,
            admin,
        )
    except rotulo_dataset_service.RotuloDatasetError as exc:
        await db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
