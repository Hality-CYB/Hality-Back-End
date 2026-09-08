"""Testes unitários para o backend de autenticação JWT (app/core/security.py)."""

from app.core.security import auth_backend, get_jwt_strategy


def test_auth_backend_name() -> None:
    """Garante que o backend de autenticação tem o nome correto."""
    assert auth_backend.name == "jwt"


def test_jwt_strategy_configuration() -> None:
    """Garante que a JWTStrategy usa os parâmetros corretos do Settings."""
    strategy = get_jwt_strategy()
    assert strategy.lifetime_seconds > 0


def test_jwt_strategy_lifetime_matches_settings() -> None:
    """Garante que o lifetime do JWT corresponde ao configurado no Settings."""
    from app.core.config import get_settings

    settings = get_settings()
    strategy = get_jwt_strategy()
    expected_seconds = settings.access_token_expire_minutes * 60
    assert strategy.lifetime_seconds == expected_seconds
