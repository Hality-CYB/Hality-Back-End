"""Testes unitários para as funções de segurança (app/core/security.py)."""

from datetime import timedelta

from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)

# ---------------------------------------------------------------------------
# Hash de senha
# ---------------------------------------------------------------------------


def test_get_password_hash_is_not_plaintext() -> None:
    """Garante que o hash gerado nunca é igual à senha em texto plano."""
    password = "SenhaSegura123!"
    hashed = get_password_hash(password)
    assert hashed != password


def test_verify_password_correct() -> None:
    """Garante que a verificação retorna True para a senha correta."""
    password = "SenhaSegura123!"
    hashed = get_password_hash(password)
    assert verify_password(password, hashed) is True


def test_verify_password_wrong() -> None:
    """Garante que a verificação retorna False para senha errada."""
    hashed = get_password_hash("SenhaSegura123!")
    assert verify_password("SenhaErrada", hashed) is False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def test_create_and_decode_access_token() -> None:
    """Garante que um token criado pode ser decodificado corretamente."""
    user_id = "123e4567-e89b-12d3-a456-426614174000"
    token = create_access_token(subject=user_id)
    decoded = decode_access_token(token)
    assert decoded == user_id


def test_decode_invalid_token_returns_none() -> None:
    """Garante que um token inválido retorna None sem levantar exceção."""
    result = decode_access_token("token.invalido.mesmo")
    assert result is None


def test_decode_expired_token_returns_none() -> None:
    """Garante que um token com expiração negativa é rejeitado."""
    token = create_access_token(subject="qualquer-id", expires_delta=timedelta(seconds=-1))
    result = decode_access_token(token)
    assert result is None
