import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.diagnostic_provider import (
    InvalidDiagnosticProviderResponse,
    get_diagnostic_provider,
    validate_provider_result,
)


def _settings(**overrides):
    values = {
        "project_name": "hality-back",
        "api_v1_prefix": "/api/v1",
        "environment": "development",
        "debug": True,
        "cors_origins": ["http://localhost:3000"],
        "postgres_host": "localhost",
        "postgres_port": 5432,
        "postgres_user": "hality",
        "postgres_password": "hality",
        "postgres_db": "hality",
        "db_echo": False,
        "diagnostic_provider": "mock",
        "diagnostic_mock_level": 2,
        "diagnostic_mock_scenario": "success",
    }
    values.update(overrides)
    return Settings(**values)


def _request():
    return SimpleNamespace(
        evaluation_id=1,
        image_reference="/imagem.jpg",
        anamnesis_answers=[],
        contract_version="v1",
    )


def test_provider_mock_success():
    provider = get_diagnostic_provider(_settings())

    result = asyncio.run(provider.analyze(_request()))

    validate_provider_result(result)

    assert result.status == "completed"
    assert result.level == 2
    assert result.provider == "mock"
    assert result.model_version == "mock-v1"


def test_provider_mock_processing():
    provider = get_diagnostic_provider(_settings(diagnostic_mock_scenario="processing"))

    result = asyncio.run(provider.analyze(_request()))

    validate_provider_result(result)

    assert result.status == "processing"
    assert result.level is None
    assert result.processed_at is None


def test_provider_mock_failure():
    provider = get_diagnostic_provider(_settings(diagnostic_mock_scenario="failure"))

    result = asyncio.run(provider.analyze(_request()))

    validate_provider_result(result)

    assert result.status == "failed"
    assert result.error_code == "mock_failure"


def test_provider_mock_invalid_response():
    provider = get_diagnostic_provider(_settings(diagnostic_mock_scenario="invalid_response"))

    result = asyncio.run(provider.analyze(_request()))

    with pytest.raises(InvalidDiagnosticProviderResponse):
        validate_provider_result(result)


def test_mock_nao_pode_ser_usado_em_producao():
    with pytest.raises(ValidationError):
        _settings(
            environment="production",
            diagnostic_provider="mock",
        )
