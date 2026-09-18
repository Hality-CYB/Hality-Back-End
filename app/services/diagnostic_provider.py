from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.core.config import Settings


SUPPORTED_DIAGNOSTIC_LEVELS = frozenset({1, 2, 3})
SUPPORTED_PROVIDER_STATUSES = frozenset(
    {
        "processing",
        "completed",
        "failed",
    }
)


@dataclass(frozen=True, slots=True)
class DiagnosticRequest:
    evaluation_id: int
    image_reference: str
    anamnesis_answers: dict[str, Any] | list[dict[str, Any]]
    contract_version: str = "v1"


@dataclass(frozen=True, slots=True)
class DiagnosticProviderResult:
    status: str
    provider: str
    model_version: str
    level: int | None = None
    score: float | None = None
    confidence: float | None = None
    processed_at: datetime | None = None
    error_code: str | None = None


class DiagnosticProvider(Protocol):
    async def analyze(
        self,
        request: DiagnosticRequest,
    ) -> DiagnosticProviderResult: ...


class DiagnosticProviderError(Exception):
    pass


class InvalidDiagnosticProviderResponse(DiagnosticProviderError):
    pass


class UnsupportedDiagnosticProviderError(DiagnosticProviderError):
    pass


def validate_provider_result(
    result: DiagnosticProviderResult,
) -> None:
    if result.status not in SUPPORTED_PROVIDER_STATUSES:
        raise InvalidDiagnosticProviderResponse("Status retornado pelo provider é inválido.")

    if not result.provider.strip():
        raise InvalidDiagnosticProviderResponse("Provider não informado.")

    if not result.model_version.strip():
        raise InvalidDiagnosticProviderResponse("Versão do modelo não informada.")

    if result.confidence is not None and not 0 <= result.confidence <= 1:
        raise InvalidDiagnosticProviderResponse("Confidence deve estar entre 0 e 1.")

    if result.status == "completed":
        if result.level not in SUPPORTED_DIAGNOSTIC_LEVELS:
            raise InvalidDiagnosticProviderResponse("Nível retornado pelo provider é inválido.")

        if result.processed_at is None:
            raise InvalidDiagnosticProviderResponse(
                "Resultado concluído sem data de processamento."
            )

        if result.error_code is not None:
            raise InvalidDiagnosticProviderResponse("Resultado concluído não pode conter erro.")

        return

    if result.level is not None:
        raise InvalidDiagnosticProviderResponse("Resultado não concluído não pode conter nível.")

    if result.score is not None:
        raise InvalidDiagnosticProviderResponse("Resultado não concluído não pode conter score.")

    if result.confidence is not None:
        raise InvalidDiagnosticProviderResponse(
            "Resultado não concluído não pode conter confidence."
        )

    if result.status == "processing":
        if result.processed_at is not None:
            raise InvalidDiagnosticProviderResponse(
                "Resultado em processamento não pode ter data de processamento."
            )

        if result.error_code is not None:
            raise InvalidDiagnosticProviderResponse(
                "Resultado em processamento não pode conter erro."
            )

        return

    if result.processed_at is None:
        raise InvalidDiagnosticProviderResponse("Falha sem data de processamento.")

    if not result.error_code:
        raise InvalidDiagnosticProviderResponse("Falha sem código de erro.")


def get_diagnostic_provider(
    settings: "Settings",
) -> DiagnosticProvider:
    if settings.diagnostic_provider == "mock":
        from app.services.mock_diagnostic_provider import (
            MockDiagnosticProvider,
        )

        return MockDiagnosticProvider(
            level=settings.diagnostic_mock_level,
            scenario=settings.diagnostic_mock_scenario,
        )

    raise UnsupportedDiagnosticProviderError(
        f"Diagnostic provider não suportado: {settings.diagnostic_provider}"
    )
