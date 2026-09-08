"""Backend de autenticação JWT via fastapi-users."""

from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy

from app.core.config import get_settings

bearer_transport = BearerTransport(tokenUrl="/api/v1/auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy:
    """Retorna a estratégia JWT com a chave secreta e tempo de expiração do Settings."""
    settings = get_settings()
    return JWTStrategy(
        secret=settings.secret_key,
        lifetime_seconds=settings.access_token_expire_minutes * 60,
    )


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)
