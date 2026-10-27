from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentAdminDep, DbSession, require_admin
from app.schemas.dataset_export import DatasetExportRequest
from app.services import dataset_export_service

router = APIRouter(
    prefix="/admin/datasets",
    tags=["admin-datasets"],
    dependencies=[Depends(require_admin)],
)


@router.post("/exports", status_code=status.HTTP_200_OK)
async def exportar_dataset(
    payload: DatasetExportRequest, admin: CurrentAdminDep, db: DbSession
) -> StreamingResponse:
    try:
        artifact = await dataset_export_service.exportar(db, admin, payload.diagnostico_ids)
    except dataset_export_service.DatasetExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return StreamingResponse(
        artifact.chunks(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )
