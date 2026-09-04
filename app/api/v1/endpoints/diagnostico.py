from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.deps import CurrentPatientIdDep, DiagnosticoServiceDep
from app.schemas.diagnostico import (
    DiagnosticoGetResponse,
    DiagnosticoPostResponse,
    ParametrosCaptura,
)
from app.services.diagnostico_service import (
    AnamneseJaUtilizadaError,
    AnamneseNaoEncontradaError,
    ArquivoMuitoGrandeError,
    DiagnosticoAcessoNegadoError,
    DiagnosticoNaoEncontradoError,
    ImagemInvalidaError,
)

router = APIRouter(
    prefix="/diagnosticos",
    tags=["diagnosticos"],
)


@router.post(
    "",
    response_model=DiagnosticoPostResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def criar_diagnostico(
    anamnese_id: Annotated[int, Form()],
    imagem: Annotated[UploadFile, File()],
    parametros_captura: Annotated[str, Form()],
    paciente_id: CurrentPatientIdDep,
    service: DiagnosticoServiceDep,
) -> DiagnosticoPostResponse | JSONResponse:
    try:
        parametros = ParametrosCaptura.model_validate_json(
            parametros_captura
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="parametros_captura deve ser um JSON válido.",
        ) from exc

    imagem_bytes = await imagem.read()

    try:
        return service.criar_diagnostico(
            paciente_id=paciente_id,
            anamnese_id=anamnese_id,
            imagem_bytes=imagem_bytes,
            imagem_content_type=imagem.content_type,
            parametros_captura=parametros,
        )

    except ImagemInvalidaError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"motivo": exc.motivo},
        )

    except AnamneseNaoEncontradaError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Anamnese não encontrada.",
        ) from exc

    except ArquivoMuitoGrandeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Arquivo acima do tamanho máximo permitido.",
        ) from exc

    except AnamneseJaUtilizadaError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Anamnese já vinculada a outro diagnóstico.",
        ) from exc


@router.get(
    "/{diagnostico_id}",
    response_model=DiagnosticoGetResponse,
)
def obter_diagnostico(
    diagnostico_id: int,
    paciente_id: CurrentPatientIdDep,
    service: DiagnosticoServiceDep,
) -> DiagnosticoGetResponse:
    try:
        return service.obter_diagnostico(
            diagnostico_id=diagnostico_id,
            paciente_id=paciente_id,
        )

    except DiagnosticoNaoEncontradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diagnóstico não encontrado.",
        ) from exc

    except DiagnosticoAcessoNegadoError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Diagnóstico pertence a outro paciente.",
        ) from exc