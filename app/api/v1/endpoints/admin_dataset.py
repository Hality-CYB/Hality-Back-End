from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentAdminDep, DbSession, require_admin
from app.auth.policies import CORRELATION_HEADER, definir_correlation_id
from app.db import auditoria_queries
from app.schemas.dataset_export import DatasetExportRequest
from app.services import dataset_export_service

router = APIRouter(
    prefix="/admin/datasets",
    tags=["admin-datasets"],
    dependencies=[Depends(require_admin)],
)


@router.post("/exports", status_code=status.HTTP_200_OK)
async def exportar_dataset(
    payload: DatasetExportRequest,
    admin: CurrentAdminDep,
    db: DbSession,
    correlation_header: str | None = Header(default=None, alias=CORRELATION_HEADER),
):
    correlation_id = definir_correlation_id(correlation_header)
    metadata = {"correlation_id": correlation_id, "registros": 0, "imagens": 0}
    try:
        resultado = await dataset_export_service.criar_exportacao(db, payload.diagnostico_ids)
        metadata.update({"registros": resultado.registros, "imagens": resultado.imagens})
        await auditoria_queries.registrar_acesso(
            db,
            actor=admin,
            action="dataset.exportacao",
            resource="dataset",
            resource_id="lote",
            result="sucesso",
            metadata=metadata,
        )
        await db.commit()
    except dataset_export_service.DatasetExportError as exc:
        await db.rollback()
        await auditoria_queries.registrar_acesso(
            db,
            actor=admin,
            action="dataset.exportacao",
            resource="dataset",
            resource_id="lote",
            result="falha",
            metadata={**metadata, "resultado": exc.__class__.__name__},
        )
        await db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.public_detail) from exc
    except Exception as exc:
        await db.rollback()
        await auditoria_queries.registrar_acesso(
            db,
            actor=admin,
            action="dataset.exportacao",
            resource="dataset",
            resource_id="lote",
            result="falha",
            metadata={**metadata, "resultado": "erro_interno"},
        )
        await db.commit()
        raise HTTPException(
            status_code=500, detail="não foi possível preparar a exportação"
        ) from exc

    headers = {
        CORRELATION_HEADER: correlation_id,
        "Content-Disposition": (
            f'attachment; filename="hality-dataset-{datetime.now(UTC):%Y%m%d}.zip"'
        ),
    }

    async def stream():
        try:
            while chunk := resultado.arquivo.read(1024 * 1024):
                yield chunk
        finally:
            resultado.arquivo.close()

    return StreamingResponse(stream(), media_type="application/zip", headers=headers)
