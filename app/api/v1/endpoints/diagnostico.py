import json
from typing import Annotated

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from app.api.deps import (
    CurrentClinicalUser,
    CurrentPatientDep,
    DbSession,
    OptionalClinicalUser,
)
from app.schemas.diagnostico import (
    ConfirmarUploadDiagnosticoRequest,
    DiagnosticoCriadoResponse,
    DiagnosticoListResponse,
    DiagnosticoPacienteDetalhe,
    UploadDiagnosticoRequest,
    UploadDiagnosticoResponse,
)
from app.services import consentimento_service, diagnostico_service, diagnostico_storage

router = APIRouter(
    prefix="/diagnosticos",
    tags=["diagnostico"],
)


@router.get(
    "/imagens/{nome_arquivo}",
    include_in_schema=False,
)
async def obter_imagem(
    nome_arquivo: str,
    usuario: OptionalClinicalUser,
    db: DbSession,
    expira: Annotated[int | None, Query()] = None,
    assinatura: Annotated[str | None, Query()] = None,
) -> Response:
    # Duas formas de acesso: Bearer (policy) ou `expira`+`assinatura`, a URL que
    # `GET /diagnosticos/{id}` devolve para o front usar em <img> (sem Bearer).
    try:
        leitura = await diagnostico_service.obter_leitura_imagem(
            db=db,
            usuario=usuario,
            nome_arquivo=nome_arquivo,
            expira_em=expira,
            assinatura=assinatura,
        )

    except diagnostico_service.ImagemSemCredencialError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    except diagnostico_service.ImagemNaoEncontradaError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="imagem não encontrada",
        ) from exc

    if isinstance(leitura, diagnostico_storage.UrlAssinada):
        # Foto de saúde: o redirect nunca fica em cache.
        return RedirectResponse(
            leitura.url,
            status_code=status.HTTP_302_FOUND,
            headers={"Cache-Control": "no-store"},
        )

    return FileResponse(leitura.caminho)


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


def _erro_de_validacao(campo: str, tipo: str = "missing") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[{"type": tipo, "loc": ["body", campo], "msg": "Field required"}],
    )


def _traduzir_erro_de_envio(exc: Exception) -> JSONResponse | HTTPException:
    if isinstance(
        exc, diagnostico_service.ImagemInvalidaError | diagnostico_service.UploadInvalidoError
    ):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"motivo": exc.motivo},
        )

    if isinstance(exc, diagnostico_service.ArquivoMuitoGrandeError):
        return HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=("arquivo acima do tamanho máximo permitido"),
        )

    if isinstance(exc, diagnostico_service.AnamneseNaoEncontradaError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="anamnese não encontrada",
        )

    if isinstance(exc, consentimento_service.TratamentoNaoVigenteError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "consentimento para tratamento de dados de saúde não vigente "
                "(revogado ou termo desatualizado)"
            ),
        )

    if isinstance(exc, diagnostico_service.AnamneseJaUtilizadaError):
        # 409 com o diagnóstico existente: retry/duplo envio não duplica nada
        # e o cliente retoma o acompanhamento pelo id devolvido.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "anamnese já vinculada a outro diagnóstico",
                "diagnostico_id": exc.diagnostico.id,
                "status": exc.diagnostico.status,
            },
        )

    raise exc


_ERROS_DE_ENVIO = (
    diagnostico_service.ImagemInvalidaError,
    diagnostico_service.UploadInvalidoError,
    diagnostico_service.ArquivoMuitoGrandeError,
    diagnostico_service.AnamneseNaoEncontradaError,
    consentimento_service.TratamentoNaoVigenteError,
    diagnostico_service.AnamneseJaUtilizadaError,
)


@router.post("/upload", response_model=UploadDiagnosticoResponse)
async def preparar_upload(
    payload: UploadDiagnosticoRequest,
    usuario: CurrentClinicalUser,
    db: DbSession,
) -> UploadDiagnosticoResponse | JSONResponse:
    """Alvo (formato presigned POST) para o navegador enviar a foto direto ao storage."""
    try:
        alvo, token = await diagnostico_service.preparar_upload(
            db=db,
            usuario=usuario,
            anamnese_id=payload.anamnese_id,
            content_type=payload.content_type,
        )
    except _ERROS_DE_ENVIO as exc:
        resposta = _traduzir_erro_de_envio(exc)
        if isinstance(resposta, HTTPException):
            raise resposta from exc
        return resposta

    return UploadDiagnosticoResponse(url=alvo.url, fields=alvo.fields, upload_token=token)


_CORPOS_DO_POST = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": ConfirmarUploadDiagnosticoRequest.model_json_schema(),
            },
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["anamnese_id", "imagem", "parametros_captura"],
                    "properties": {
                        "anamnese_id": {"type": "integer"},
                        "imagem": {"type": "string", "format": "binary"},
                        "parametros_captura": {"type": "string"},
                    },
                },
            },
        },
    },
}


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DiagnosticoCriadoResponse,
    openapi_extra=_CORPOS_DO_POST,
)
async def criar_diagnostico(
    request: Request,
    # Paciente na autoavaliação ou profissional vinculado (US-090). O titular vem
    # sempre da anamnese, e o acesso a ela é checado no service.
    usuario: CurrentClinicalUser,
    db: DbSession,
) -> DiagnosticoCriadoResponse | JSONResponse:
    """Cria o diagnóstico.

    JSON `{anamnese_id, upload_token, parametros_captura}`: confirma a foto já
    enviada ao alvo de `POST /diagnosticos/upload`. Multipart (`anamnese_id`,
    `imagem`, `parametros_captura`): fluxo antigo, em que a foto passa pela API.
    """
    tipo = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()

    try:
        if tipo == "application/json":
            return await _confirmar_envio(request, usuario, db)

        if tipo == "multipart/form-data":
            return await _criar_por_multipart(request, usuario, db)

    except _ERROS_DE_ENVIO as exc:
        resposta = _traduzir_erro_de_envio(exc)
        if isinstance(resposta, HTTPException):
            raise resposta from exc
        return resposta

    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="use multipart/form-data ou application/json",
    )


async def _confirmar_envio(
    request: Request,
    usuario: CurrentClinicalUser,
    db: DbSession,
) -> DiagnosticoCriadoResponse:
    try:
        payload = ConfirmarUploadDiagnosticoRequest.model_validate_json(await request.body())
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(include_url=False, include_context=False, include_input=False),
        ) from exc

    return await diagnostico_service.confirmar_upload(
        db=db,
        usuario=usuario,
        anamnese_id=payload.anamnese_id,
        upload_token=payload.upload_token,
        parametros_captura=payload.parametros_captura,
    )


async def _criar_por_multipart(
    request: Request,
    usuario: CurrentClinicalUser,
    db: DbSession,
) -> DiagnosticoCriadoResponse | JSONResponse:
    form = await request.form()
    anamnese_bruta = form.get("anamnese_id")
    imagem = form.get("imagem")
    parametros_captura = form.get("parametros_captura")

    if not isinstance(anamnese_bruta, str):
        raise _erro_de_validacao("anamnese_id")

    if not isinstance(imagem, UploadFile):
        raise _erro_de_validacao("imagem")

    if not isinstance(parametros_captura, str):
        raise _erro_de_validacao("parametros_captura")

    try:
        anamnese_id = int(anamnese_bruta)
    except ValueError as exc:
        raise _erro_de_validacao("anamnese_id", "int_parsing") from exc

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

    return await diagnostico_service.criar_diagnostico(
        db=db,
        usuario=usuario,
        anamnese_id=anamnese_id,
        imagem=imagem_bytes,
        content_type=imagem.content_type or "",
        parametros_captura=parametros,
    )


@router.get("/{diagnostico_id}", response_model=DiagnosticoPacienteDetalhe)
async def obter_diagnostico(
    diagnostico_id: int,
    usuario: CurrentClinicalUser,
    db: DbSession,
) -> DiagnosticoPacienteDetalhe:
    try:
        return await diagnostico_service.obter_diagnostico(
            db=db,
            usuario=usuario,
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
