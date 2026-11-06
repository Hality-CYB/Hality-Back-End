from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentAdminMutationDep, DbSession, SettingsDep
from app.auth.policies import CORRELATION_HEADER, definir_correlation_id
from app.schemas.dataset_export import DatasetExportCreate
from app.services import dataset_export_service

router = APIRouter(prefix="/admin/datasets", tags=["admin-datasets"])


async def _stream_and_cleanup(spool) -> AsyncIterator[bytes]:
    try:
        while chunk := spool.read(1024 * 1024):
            yield chunk
    finally:
        spool.close()


@router.post(
    "/exports",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"application/zip": {}}, "description": "Pacote ZIP do dataset."},
        404: {"description": "Diagnóstico inexistente na seleção."},
        409: {
            "description": (
                "Exportação desligada, ou diagnósticos não elegíveis (lista em "
                "`detail.diagnostico_ids`)."
            )
        },
        413: {"description": "Limite de itens ou de bytes excedido."},
    },
)
async def exportar_dataset(
    payload: DatasetExportCreate,
    request: Request,
    admin: CurrentAdminMutationDep,
    db: DbSession,
    settings: SettingsDep,
) -> StreamingResponse:
    correlation_id = definir_correlation_id(request.headers.get(CORRELATION_HEADER))
    try:
        spool = await dataset_export_service.gerar(
            db, admin, payload.diagnostico_ids, settings, correlation_id
        )
    except dataset_export_service.DatasetExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    response = StreamingResponse(
        _stream_and_cleanup(spool),
        media_type="application/zip",
    )
    filename = f"hality-dataset-{datetime.now(UTC):%Y%m%d}.zip"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
