from datetime import UTC, datetime

from app.services.diagnostic_provider import (
    SUPPORTED_DIAGNOSTIC_LEVELS,
    DiagnosticProviderResult,
    DiagnosticRequest,
)

SUPPORTED_MOCK_SCENARIOS = frozenset(
    {
        "success",
        "processing",
        "failure",
        "invalid_response",
    }
)


class MockDiagnosticProvider:
    def __init__(
        self,
        level: int = 2,
        scenario: str = "success",
    ) -> None:
        if level not in SUPPORTED_DIAGNOSTIC_LEVELS:
            raise ValueError("DIAGNOSTIC_MOCK_LEVEL deve ser 1, 2 ou 3.")

        if scenario not in SUPPORTED_MOCK_SCENARIOS:
            raise ValueError("Cenário do mock inválido.")

        self.level = level
        self.scenario = scenario

    async def analyze(
        self,
        request: DiagnosticRequest,
    ) -> DiagnosticProviderResult:
        if not request.image_reference:
            return DiagnosticProviderResult(
                status="failed",
                provider="mock",
                model_version="mock-v1",
                processed_at=datetime.now(UTC),
                error_code="missing_image",
            )

        if self.scenario == "processing":
            return DiagnosticProviderResult(
                status="processing",
                provider="mock",
                model_version="mock-v1",
            )

        if self.scenario == "failure":
            return DiagnosticProviderResult(
                status="failed",
                provider="mock",
                model_version="mock-v1",
                processed_at=datetime.now(UTC),
                error_code="mock_failure",
            )

        if self.scenario == "invalid_response":
            return DiagnosticProviderResult(
                status="completed",
                provider="",
                model_version="",
                level=999,
                processed_at=datetime.now(UTC),
            )

        return DiagnosticProviderResult(
            status="completed",
            provider="mock",
            model_version="mock-v1",
            level=self.level,
            score=None,
            confidence=None,
            processed_at=datetime.now(UTC),
        )
