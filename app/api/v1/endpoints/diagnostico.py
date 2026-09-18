import json
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, JSONResponse

from app.api.deps import CurrentPatientDep, DbSession
from app.schemas.diagnostico import DiagnosticoListResponse
from app.services import diagnostico_service, diagnostico_storage

router = APIRouter(
    prefix="/diagnosticos",
    tags=["diagnostico"],
)


@router.get(
    "/imagens/{nome_arquivo}",
    include_in_schema=False,
)
def obter_imagem(nome_arquivo: str) -> FileResponse:
    caminho = diagnostico_storage.resolver_caminho(nome_arquivo)

    if caminho is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="imagem não encontrada",
        )

    return FileResponse(caminho)


@router.get("", response_model=DiagnosticoListResponse)
async def listar_diagnosticos(
    paciente_id: CurrentPatientDep,
    db: DbSession,
    data_inicio: Annotated[str | None, Query()] = None,
    data_fim: Annotated[str | None, Query()] = None,
    status_diagnostico: Annotated[str | None, Query(alias="status")] = None,
    pagina: Annotated[int, Query()] = 1,
    limite: Annotated[int, Query()] = 20,
    ordem: Annotated[str, Query()] = "data_desc",
) -> DiagnosticoListResponse:
    try:
        return await diagnostico_service.listar_diagnosticos(
            db=db,
            paciente_id=paciente_id,
            data_inicio=data_inicio,
            data_fim=data_fim,
            status=status_diagnostico,
            pagina=pagina,
            limite=limite,
            ordem=ordem,
        )

    except diagnostico_service.DiagnosticoFiltroInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.motivo,
        ) from exc


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=None,
)
async def criar_diagnostico(
    anamnese_id: Annotated[int, Form()],
    imagem: Annotated[UploadFile, File()],
    parametros_captura: Annotated[str, Form()],
    paciente_id: CurrentPatientDep,
    db: DbSession,
) -> dict[str, Any] | JSONResponse:
    try:
        parametros = json.loads(parametros_captura)

        if not isinstance(parametros, dict):
            raise ValueError

    except (json.JSONDecodeError, ValueError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"motivo": ("parametros_captura deve ser um objeto JSON válido.")},
        )

    imagem_bytes = await imagem.read(diagnostico_storage.MAX_IMAGE_BYTES + 1)

    try:
        return await diagnostico_service.criar_diagnostico(
            db=db,
            paciente_id=paciente_id,
            anamnese_id=anamnese_id,
            imagem=imagem_bytes,
            content_type=imagem.content_type or "",
            parametros_captura=parametros,
        )

    except diagnostico_service.ImagemInvalidaError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"motivo": exc.motivo},
        )

    except diagnostico_service.ArquivoMuitoGrandeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=("arquivo acima do tamanho máximo permitido"),
        ) from exc

    except diagnostico_service.AnamneseNaoEncontradaError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="anamnese não encontrada",
        ) from exc

    except diagnostico_service.AnamneseJaUtilizadaError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=("anamnese já vinculada a outro diagnóstico"),
        ) from exc


@router.get("/{diagnostico_id}")
async def obter_diagnostico(
    diagnostico_id: int,
    paciente_id: CurrentPatientDep,
    db: DbSession,
) -> dict[str, Any]:
    try:
        return await diagnostico_service.obter_diagnostico(
            db=db,
            paciente_id=paciente_id,
            diagnostico_id=diagnostico_id,
        )

    except diagnostico_service.DiagnosticoNaoEncontradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="diagnóstico não encontrado",
        ) from exc

    except diagnostico_service.DiagnosticoAcessoNegadoError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("diagnóstico pertence a outro paciente"),
        ) from exc

    except diagnostico_service.AnamneseNaoEncontradaError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=("anamnese do diagnóstico não encontrada"),
        ) from exc
