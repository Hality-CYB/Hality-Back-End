"""Testes unitários para o módulo de segurança (app/core/security.py)."""

import jwt
import pytest

from app.core.security import (
    ALGORITHM,
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)


def test_password_hashing() -> None:
    """Garante que a senha é hashificada corretamente e verificada com sucesso."""
    raw_password = "MinhaSenhaSegura123!"
    hashed = get_password_hash(raw_password)

    assert hashed != raw_password
    assert verify_password(raw_password, hashed) is True
    assert verify_password("SenhaIncorreta", hashed) is False


def test_jwt_token_create_and_decode() -> None:
    """Garante que um token JWT pode ser criado e decodificado com os dados corretos."""
    data = {"sub": "paciente@hality.com"}
    token = create_access_token(data)

    assert isinstance(token, str)

    payload = decode_access_token(token)
    assert payload["sub"] == "paciente@hality.com"
    assert "exp" in payload


def test_jwt_token_invalid_signature() -> None:
    """Garante que decodificar token com assinatura/chave errada lança exceção."""
    data = {"sub": "paciente@hality.com"}
    token = create_access_token(data)

    with pytest.raises(jwt.InvalidTokenError):
        jwt.decode(token, "chave-errada", algorithms=[ALGORITHM])
