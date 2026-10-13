import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentProfessional, CurrentProfessionalDep, DbSession
from app.schemas.profissionais import ResumoProfissionalResponse
from app.schemas.profissional_diagnostico import (
    DiagnosticoProfissionalDetalhe,
    DiagnosticoProfissionalListResponse,
    RevisaoProfissionalInput,
    RevisaoProfissionalResponse,
)
from app.services import diagnostico_service, profissional_service
from app.services.periodo import TimezoneInvalidoError, resolver_periodo

router = APIRouter(
    prefix="/profissional",
    tags=["profissional"],
)


@router.get(
    "/resumo",
    response_model=ResumoProfissionalResponse,
)
async def obter_resumo(
    profissional: CurrentProfessionalDep,
    db: DbSession,
    inicio: Annotated[datetime | None, Query()] = None,
    fim: Annotated[datetime | None, Query()] = None,
    timezone: Annotated[str, Query()] = "UTC",
) -> ResumoProfissionalResponse:
    try:
        inicio_efetivo, fim_efetivo = resolver_periodo(inicio, fim, timezone)
    except TimezoneInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="timezone invalido",
        ) from exc

    try:
        return await profissional_service.montar_resumo(
            db=db,
            profissional_id=profissional.id,
            inicio=inicio_efetivo,
            fim=fim_efetivo,
            timezone=timezone,
        )

    except profissional_service.PeriodoInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="periodo invalido",
        ) from exc


@router.get(
    "/diagnosticos",
    response_model=DiagnosticoProfissionalListResponse,
)
async def listar_diagnosticos(
    profissional: CurrentProfessional,
    db: DbSession,
    paciente_id: Annotated[
        uuid.UUID | None,
        Query(),
    ] = None,
    status_diagnostico: Annotated[
        str | None,
        Query(alias="status"),
    ] = None,
    data_inicio: Annotated[
        str | None,
        Query(),
    ] = None,
    data_fim: Annotated[
        str | None,
        Query(),
    ] = None,
    pagina: Annotated[
        int,
        Query(),
    ] = 1,
    limite: Annotated[
        int,
        Query(),
    ] = 20,
    ordem: Annotated[
        str,
        Query(),
    ] = "data_desc",
) -> DiagnosticoProfissionalListResponse:
    """Lista diagnósticos dos pacientes vinculados ao profissional.

    O `paciente_id`, quando informado, é somente um filtro. A autorização
    continua dependendo de vínculo ativo entre profissional e paciente.
    """

    try:
        return await diagnostico_service.listar_diagnosticos_profissional(
            db=db,
            profissional_id=profissional.id,
            paciente_id=paciente_id,
            status=status_diagnostico,
            data_inicio=data_inicio,
            data_fim=data_fim,
            pagina=pagina,
            limite=limite,
            ordem=ordem,
        )

    except diagnostico_service.DiagnosticoFiltroInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.motivo,
        ) from exc


@router.get(
    "/diagnosticos/{diagnostico_id}",
    response_model=DiagnosticoProfissionalDetalhe,
)
async def obter_diagnostico(
    diagnostico_id: int,
    profissional: CurrentProfessional,
    db: DbSession,
) -> DiagnosticoProfissionalDetalhe:
    """Retorna o detalhe clínico de um diagnóstico acessível ao profissional."""

    try:
        return await diagnostico_service.obter_diagnostico_profissional(
            db=db,
            profissional=profissional,
            diagnostico_id=diagnostico_id,
        )

    except diagnostico_service.DiagnosticoNaoEncontradoError as exc:
        # Diagnóstico inexistente e diagnóstico sem vínculo ativo são
        # indistinguíveis nesta rota para evitar enumeração de ids.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="diagnóstico não encontrado",
        ) from exc

    except diagnostico_service.AnamneseNaoEncontradaError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="anamnese do diagnóstico não encontrada",
        ) from exc


@router.patch(
    "/diagnosticos/{diagnostico_id}/revisao",
    response_model=RevisaoProfissionalResponse,
)
async def revisar_diagnostico(
    diagnostico_id: int,
    payload: RevisaoProfissionalInput,
    profissional: CurrentProfessional,
    db: DbSession,
) -> RevisaoProfissionalResponse:
    """Cria uma nova versão append-only da revisão profissional."""

    try:
        return await diagnostico_service.revisar_diagnostico_profissional(
            db=db,
            profissional=profissional,
            diagnostico_id=diagnostico_id,
            classificacao_codigo=payload.classificacao,
            observacao=payload.observacao,
            version=payload.version,
        )

    except diagnostico_service.DiagnosticoNaoEncontradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="diagnóstico não encontrado",
        ) from exc

    except diagnostico_service.ClassificacaoRevisaoInvalidaError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="classificação inválida",
        ) from exc

    except diagnostico_service.DiagnosticoNaoRevisavelError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="diagnóstico não está disponível para revisão",
        ) from exc

    except diagnostico_service.DiagnosticoRevisaoConflitoError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "a revisão foi alterada por outra operação; "
                "atualize o diagnóstico e tente novamente"
            ),
        ) from exc
