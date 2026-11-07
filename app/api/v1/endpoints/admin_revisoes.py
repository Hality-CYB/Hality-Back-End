from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentAdminMutationDep, DbSession
from app.schemas.profissional_diagnostico import (
    RevisaoProfissionalInput,
    RevisaoProfissionalResponse,
)
from app.services import diagnostico_service

router = APIRouter(prefix="/admin/diagnosticos", tags=["admin-diagnosticos"])


@router.patch(
    "/{diagnostico_id}/revisao",
    response_model=RevisaoProfissionalResponse,
)
async def reclassificar_diagnostico(
    diagnostico_id: int,
    payload: RevisaoProfissionalInput,
    admin: CurrentAdminMutationDep,
    db: DbSession,
) -> RevisaoProfissionalResponse:
    """Reclassifica o resultado do paciente como uma nova versão da revisão."""

    try:
        return await diagnostico_service.reclassificar_diagnostico_admin(
            db=db,
            admin=admin,
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
