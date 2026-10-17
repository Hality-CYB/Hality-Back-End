"""Adapter do Google: PKCE, troca de código e validação do ID token (sem rede real)."""

import base64
import hashlib
import json
import time
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pydantic import SecretStr

from app.auth import google
from app.auth.google import (
    CodigoRejeitadoError,
    EmailNaoVerificadoError,
    GoogleOAuthProvider,
    IdentidadeGoogle,
    IdTokenInvalidoError,
    ProvedorIndisponivelError,
)
from app.core.config import get_settings

CLIENT_ID = "cliente-teste.apps.googleusercontent.com"
CLIENT_SECRET = "segredo-do-cliente-jamais-no-frontend"
REDIRECT_URI = "http://localhost:8000/api/v1/auth/google/callback"
NONCE = "nonce-esperado"
VERIFIER = "v" * 64


def _chave() -> tuple[rsa.RSAPrivateKey, dict]:
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = RSAAlgorithm.to_jwk(privada.public_key(), as_dict=True)
    return privada, {**jwk, "kid": "kid-1", "alg": "RS256", "use": "sig"}


CHAVE_PRIVADA, JWK_PUBLICO = _chave()
OUTRA_CHAVE_PRIVADA, _ = _chave()


def _claims(**sobrescritas) -> dict:
    agora = int(time.time())
    base = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": "Maria.Silva@Gmail.com",
        "email_verified": True,
        "name": "Maria Silva",
        "nonce": NONCE,
        "iat": agora,
        "exp": agora + 300,
    }
    base.update(sobrescritas)
    return {chave: valor for chave, valor in base.items() if valor is not None}


def _token(claims: dict | None = None, chave=CHAVE_PRIVADA, **cabecalho) -> str:
    return jwt.encode(
        claims or _claims(),
        chave,
        algorithm="RS256",
        headers={"kid": "kid-1", **cabecalho},
    )


class Google:
    """Servidor falso do Google atrás de um MockTransport."""

    def __init__(self) -> None:
        self.id_token: str | None = _token()
        self.token_status = 200
        self.token_corpo: dict | None = None
        self.jwks = {"keys": [JWK_PUBLICO]}
        self.jwks_status = 200
        self.chamadas: list[httpx.Request] = []
        self.erro_de_rede: Exception | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.chamadas.append(request)
        if self.erro_de_rede is not None:
            raise self.erro_de_rede
        if str(request.url) == google.GOOGLE_TOKEN_URL:
            corpo = self.token_corpo
            if corpo is None:
                corpo = {"id_token": self.id_token, "access_token": "nao-deve-ser-usado"}
            return httpx.Response(self.token_status, json=corpo)
        if str(request.url) == google.GOOGLE_JWKS_URL:
            return httpx.Response(self.jwks_status, json=self.jwks)
        return httpx.Response(404)

    def provider(self) -> GoogleOAuthProvider:
        settings = get_settings().model_copy(
            update={
                "google_client_id": CLIENT_ID,
                "google_client_secret": SecretStr(CLIENT_SECRET),
                "google_redirect_uri": REDIRECT_URI,
                "google_frontend_redirect_url": "http://localhost:3000/login/google",
            }
        )
        return GoogleOAuthProvider(settings, transport=httpx.MockTransport(self))


@pytest.fixture
def servidor() -> Google:
    return Google()


async def _obter(servidor: Google) -> IdentidadeGoogle:
    return await servidor.provider().obter_identidade(
        code="codigo-do-google", code_verifier=VERIFIER, nonce=NONCE
    )


# ---------------------------------------------------------------------------
# PKCE e URL de autorização
# ---------------------------------------------------------------------------


def test_code_challenge_e_o_sha256_base64url_do_verifier() -> None:
    esperado = (
        base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
    )

    assert google.code_challenge_s256(VERIFIER) == esperado


def test_code_verifier_respeita_o_tamanho_da_rfc_7636() -> None:
    verifier = google.gerar_code_verifier()

    assert 43 <= len(verifier) <= 128
    assert verifier != google.gerar_code_verifier()


def test_url_de_autorizacao_usa_state_nonce_e_pkce_s256_sem_segredo(servidor: Google) -> None:
    url = servidor.provider().authorization_url(state="st", nonce=NONCE, code_verifier=VERIFIER)

    partes = urlparse(url)
    consulta = {k: v[0] for k, v in parse_qs(partes.query).items()}
    assert f"{partes.scheme}://{partes.netloc}{partes.path}" == google.GOOGLE_AUTH_URL
    assert consulta["client_id"] == CLIENT_ID
    assert consulta["redirect_uri"] == REDIRECT_URI
    assert consulta["response_type"] == "code"
    assert consulta["scope"] == "openid email profile"
    assert consulta["state"] == "st"
    assert consulta["nonce"] == NONCE
    assert consulta["code_challenge_method"] == "S256"
    assert consulta["code_challenge"] == google.code_challenge_s256(VERIFIER)
    assert VERIFIER not in url
    assert CLIENT_SECRET not in url


# ---------------------------------------------------------------------------
# Troca de código
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_troca_envia_verifier_e_segredo_no_corpo_do_post(servidor: Google) -> None:
    identidade = await _obter(servidor)

    assert identidade == IdentidadeGoogle(
        subject="1234567890", email="maria.silva@gmail.com", nome="Maria Silva"
    )
    troca = next(c for c in servidor.chamadas if str(c.url) == google.GOOGLE_TOKEN_URL)
    corpo = parse_qs(troca.content.decode())
    assert troca.method == "POST"
    assert corpo["grant_type"] == ["authorization_code"]
    assert corpo["code"] == ["codigo-do-google"]
    assert corpo["code_verifier"] == [VERIFIER]
    assert corpo["client_secret"] == [CLIENT_SECRET]
    assert CLIENT_SECRET not in str(troca.url)


@pytest.mark.asyncio
async def test_invalid_grant_vira_codigo_rejeitado(servidor: Google) -> None:
    servidor.token_status = 400
    servidor.token_corpo = {"error": "invalid_grant"}

    with pytest.raises(CodigoRejeitadoError):
        await _obter(servidor)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "corpo"),
    [
        (500, {}),
        (503, {}),
        (401, {"error": "invalid_client"}),
        (400, {"error": "redirect_uri_mismatch"}),
    ],
)
async def test_provedor_com_erro_vira_indisponivel(
    servidor: Google, status: int, corpo: dict
) -> None:
    servidor.token_status = status
    servidor.token_corpo = corpo

    with pytest.raises(ProvedorIndisponivelError):
        await _obter(servidor)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "erro", [httpx.ConnectError("sem rede"), httpx.ReadTimeout("lento")], ids=["rede", "timeout"]
)
async def test_falha_de_rede_vira_indisponivel(servidor: Google, erro: Exception) -> None:
    servidor.erro_de_rede = erro

    with pytest.raises(ProvedorIndisponivelError):
        await _obter(servidor)


@pytest.mark.asyncio
async def test_resposta_sem_id_token_e_invalida(servidor: Google) -> None:
    servidor.token_corpo = {"access_token": "x"}

    with pytest.raises(IdTokenInvalidoError):
        await _obter(servidor)


@pytest.mark.asyncio
async def test_jwks_indisponivel_vira_indisponivel(servidor: Google) -> None:
    servidor.jwks_status = 503

    with pytest.raises(ProvedorIndisponivelError):
        await _obter(servidor)


# ---------------------------------------------------------------------------
# Validação do ID token
# ---------------------------------------------------------------------------

_INVALIDOS: dict[str, Callable[[], str]] = {
    "audience_errada": lambda: _token(_claims(aud="outro-cliente")),
    "issuer_errado": lambda: _token(_claims(iss="https://evil.example.com")),
    "expirado": lambda: _token(_claims(exp=int(time.time()) - 3600)),
    "sem_exp": lambda: _token(_claims(exp=None)),
    "sem_iat": lambda: _token(_claims(iat=None)),
    "sem_sub": lambda: _token(_claims(sub=None)),
    "sub_vazio": lambda: _token(_claims(sub="")),
    "sem_email": lambda: _token(_claims(email=None)),
    "nonce_errado": lambda: _token(_claims(nonce="outro")),
    "sem_nonce": lambda: _token(_claims(nonce=None)),
    "assinatura_de_outra_chave": lambda: _token(chave=OUTRA_CHAVE_PRIVADA),
    "kid_desconhecido": lambda: _token(kid="kid-que-nao-existe"),
    "sem_kid": lambda: jwt.encode(_claims(), CHAVE_PRIVADA, algorithm="RS256"),
    "alg_none": lambda: jwt.encode(_claims(), key=None, algorithm="none", headers={"kid": "kid-1"}),
    "alg_hs256": lambda: jwt.encode(
        _claims(),
        "segredo-simetrico-com-mais-de-32-bytes!!",
        algorithm="HS256",
        headers={"kid": "kid-1"},
    ),
    "lixo": lambda: "isto.nao.e-um-jwt",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", list(_INVALIDOS))
async def test_id_token_invalido_e_recusado(servidor: Google, caso: str) -> None:
    servidor.id_token = _INVALIDOS[caso]()

    with pytest.raises(IdTokenInvalidoError):
        await _obter(servidor)


@pytest.mark.asyncio
@pytest.mark.parametrize("valor", [False, None, "false", 0])
async def test_email_nao_verificado_e_recusado(servidor: Google, valor) -> None:
    servidor.id_token = _token(_claims(email_verified=valor))

    with pytest.raises(EmailNaoVerificadoError):
        await _obter(servidor)


@pytest.mark.asyncio
async def test_issuer_sem_esquema_tambem_e_aceito(servidor: Google) -> None:
    servidor.id_token = _token(_claims(iss="accounts.google.com"))

    assert (await _obter(servidor)).subject == "1234567890"


@pytest.mark.asyncio
async def test_email_verified_como_string_true_e_aceito(servidor: Google) -> None:
    servidor.id_token = _token(_claims(email_verified="true"))

    assert (await _obter(servidor)).email == "maria.silva@gmail.com"


@pytest.mark.asyncio
async def test_nome_ausente_usa_a_parte_local_do_email(servidor: Google) -> None:
    servidor.id_token = _token(_claims(name=None))

    assert (await _obter(servidor)).nome == "maria.silva"


@pytest.mark.asyncio
async def test_jwks_fica_em_cache_e_e_rebuscado_na_rotacao_de_chave(servidor: Google) -> None:
    provider = servidor.provider()
    await provider.obter_identidade(code="c", code_verifier=VERIFIER, nonce=NONCE)
    await provider.obter_identidade(code="c", code_verifier=VERIFIER, nonce=NONCE)
    buscas = [c for c in servidor.chamadas if str(c.url) == google.GOOGLE_JWKS_URL]
    assert len(buscas) == 1  # segunda validação usou o cache

    # O Google rotaciona: o token novo vem com um kid que o cache ainda não tem.
    nova_privada, nova_jwk = _chave()
    servidor.jwks = {"keys": [JWK_PUBLICO, {**nova_jwk, "kid": "kid-2"}]}
    servidor.id_token = jwt.encode(
        _claims(), nova_privada, algorithm="RS256", headers={"kid": "kid-2"}
    )

    identidade = await provider.obter_identidade(code="c", code_verifier=VERIFIER, nonce=NONCE)

    assert identidade.subject == "1234567890"
    buscas = [c for c in servidor.chamadas if str(c.url) == google.GOOGLE_JWKS_URL]
    assert len(buscas) == 2


def test_resultado_da_identidade_nao_expoe_token() -> None:
    campos = {campo for campo in IdentidadeGoogle.__slots__}

    assert campos == {"subject", "email", "nome"}
    assert json.dumps(sorted(campos))  # só metadados
