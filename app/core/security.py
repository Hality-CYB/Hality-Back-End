"""Funções de segurança: hash de senha e JWT via PyJWT + pwdlib."""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import get_settings

# ---------------------------------------------------------------------------
# Hash de senha
# ---------------------------------------------------------------------------

_pwd_hash = PasswordHash([BcryptHasher()])


def get_password_hash(password: str) -> str:
    """Retorna o hash bcrypt de uma senha em texto plano."""
    return _pwd_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica se uma senha em texto plano corresponde ao hash armazenado."""
    return _pwd_hash.verify(plain_password, hashed_password)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def create_access_token(
    subject: str | Any,
    expires_delta: timedelta | None = None,
) -> str:
    """Cria um token JWT assinado com a chave secreta do Settings.

    Args:
        subject: Identificador do usuário (normalmente o UUID como string).
        expires_delta: Tempo de vida do token. Se None, usa o padrão do Settings.

    Returns:
        Token JWT como string.
    """
    settings = get_settings()
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)

    expire = datetime.now(UTC) + expires_delta
    payload = {"sub": str(subject), "exp": expire}

    return jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )


def decode_access_token(token: str) -> str | None:
    """Decodifica e valida um token JWT.

    Args:
        token: Token JWT recebido no header Authorization.

    Returns:
        O valor de ``sub`` (user_id) se o token for válido, ou ``None`` se inválido/expirado.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.algorithm],
        )
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
