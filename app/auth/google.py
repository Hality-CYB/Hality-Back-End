"""Adapter OAuth/OIDC do Google (US-012) — authorization code + PKCE.

Toda a conversa com o Google acontece aqui, no backend: o client secret nunca
sai deste módulo e o ID token é validado por completo (assinatura via JWKS do
Google, `iss`, `aud`, `exp`/`iat`, `sub`, `nonce` e `email_verified`) antes de
virar uma identidade. Nada deste módulo grava token em log ou em banco.
"""

import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.auth.google")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
GOOGLE_SCOPES = "openid email profile"

TIMEOUT_REQUISICAO = httpx.Timeout(10.0)
TOLERANCIA_RELOGIO_SEGUNDOS = 30
JWKS_TTL_SEGUNDOS = 3600


class GoogleOAuthError(Exception):
    """Base dos erros do provedor. A mensagem nunca carrega token ou perfil."""


class ProvedorIndisponivelError(GoogleOAuthError):
    """Rede, timeout, 5xx ou configuração inválida do lado do provedor."""


class CodigoRejeitadoError(GoogleOAuthError):
    """O Google recusou o código de autorização (inválido, expirado ou reutilizado)."""


class IdTokenInvalidoError(GoogleOAuthError):
    """O ID token não passou na validação (assinatura, iss, aud, exp, nonce, sub...)."""


class EmailNaoVerificadoError(GoogleOAuthError):
    """O Google não garante que o titular controla o e-mail."""


@dataclass(frozen=True, slots=True)
class IdentidadeGoogle:
    """O mínimo que o fluxo precisa do ID token — não é o perfil bruto."""

    subject: str
    email: str
    nome: str


def gerar_code_verifier() -> str:
    # 64 bytes -> 86 caracteres url-safe (RFC 7636 exige 43 a 128).
    return secrets.token_urlsafe(64)


def code_challenge_s256(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class GoogleOAuthProvider:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._jwks: dict[str, Any] | None = None
        self._jwks_expira_em = 0.0

    # -- etapa 1: URL de autorização ---------------------------------------

    def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        parametros = {
            "client_id": self._settings.google_client_id,
            "redirect_uri": self._settings.google_redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_SCOPES,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge_s256(code_verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(parametros)}"

    # -- etapa 2: código -> identidade validada ----------------------------

    async def obter_identidade(
        self, *, code: str, code_verifier: str, nonce: str
    ) -> IdentidadeGoogle:
        id_token = await self._trocar_codigo(code=code, code_verifier=code_verifier)
        claims = await self._validar_id_token(id_token, nonce=nonce)
        return self._identidade_das_claims(claims)

    def _cliente_http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TIMEOUT_REQUISICAO, transport=self._transport)

    async def _trocar_codigo(self, *, code: str, code_verifier: str) -> str:
        segredo = self._settings.google_client_secret
        dados = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "client_id": self._settings.google_client_id,
            "client_secret": segredo.get_secret_value() if segredo else "",
            "redirect_uri": self._settings.google_redirect_uri,
        }
        try:
            async with self._cliente_http() as cliente:
                resposta = await cliente.post(GOOGLE_TOKEN_URL, data=dados)
        except httpx.HTTPError as exc:
            logger.warning("google_token_endpoint_inacessivel tipo=%s", type(exc).__name__)
            raise ProvedorIndisponivelError from exc

        if resposta.status_code >= 500:
            logger.warning("google_token_endpoint_5xx status=%s", resposta.status_code)
            raise ProvedorIndisponivelError

        if resposta.status_code != 200:
            erro = _campo_erro(resposta)
            if erro == "invalid_grant":
                raise CodigoRejeitadoError
            # invalid_client / redirect_uri_mismatch etc.: problema de configuração
            # nosso, não do usuário — só o código do erro vai para o log.
            logger.error("google_token_endpoint_recusou erro=%s", erro)
            raise ProvedorIndisponivelError

        try:
            id_token = resposta.json().get("id_token")
        except ValueError as exc:
            raise ProvedorIndisponivelError from exc
        if not isinstance(id_token, str) or not id_token:
            raise IdTokenInvalidoError
        return id_token

    async def _validar_id_token(self, id_token: str, *, nonce: str) -> dict[str, Any]:
        try:
            cabecalho = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise IdTokenInvalidoError from exc

        # Só RS256: recusa `none` e algoritmos simétricos (confusão de algoritmo).
        kid = cabecalho.get("kid")
        if cabecalho.get("alg") != "RS256" or not isinstance(kid, str):
            raise IdTokenInvalidoError

        chave = await self._chave_publica(kid)
        try:
            claims = jwt.decode(
                id_token,
                chave,
                algorithms=["RS256"],
                audience=self._settings.google_client_id,
                issuer=GOOGLE_ISSUERS,
                leeway=TOLERANCIA_RELOGIO_SEGUNDOS,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise IdTokenInvalidoError from exc

        nonce_recebido = claims.get("nonce")
        if not isinstance(nonce_recebido, str) or not secrets.compare_digest(
            nonce_recebido.encode(), nonce.encode()
        ):
            raise IdTokenInvalidoError
        return claims

    async def _chave_publica(self, kid: str) -> Any:
        agora = time.monotonic()
        precisa_buscar = self._jwks is None or agora >= self._jwks_expira_em
        if precisa_buscar:
            await self._atualizar_jwks()
        chave = self._procurar_chave(kid)
        if chave is None and not precisa_buscar:
            # Rotação de chaves no Google: tenta uma vez com o JWKS novo.
            await self._atualizar_jwks()
            chave = self._procurar_chave(kid)
        if chave is None:
            raise IdTokenInvalidoError
        return chave

    def _procurar_chave(self, kid: str) -> Any | None:
        for jwk in (self._jwks or {}).get("keys", []):
            if jwk.get("kid") == kid:
                try:
                    return jwt.PyJWK(jwk).key
                except jwt.PyJWTError:
                    return None
        return None

    async def _atualizar_jwks(self) -> None:
        try:
            async with self._cliente_http() as cliente:
                resposta = await cliente.get(GOOGLE_JWKS_URL)
            resposta.raise_for_status()
            jwks = resposta.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("google_jwks_inacessivel tipo=%s", type(exc).__name__)
            raise ProvedorIndisponivelError from exc
        if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
            raise ProvedorIndisponivelError
        self._jwks = jwks
        self._jwks_expira_em = time.monotonic() + JWKS_TTL_SEGUNDOS

    @staticmethod
    def _identidade_das_claims(claims: dict[str, Any]) -> IdentidadeGoogle:
        subject = claims.get("sub")
        email = claims.get("email")
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise IdTokenInvalidoError
        if not isinstance(email, str) or "@" not in email or len(email) > 320:
            raise IdTokenInvalidoError

        verificado = claims.get("email_verified")
        if verificado is not True and verificado != "true":
            raise EmailNaoVerificadoError

        email = email.strip().lower()
        nome = claims.get("name")
        nome = nome.strip() if isinstance(nome, str) else ""
        if len(nome) < 2:
            nome = email.split("@", 1)[0]
        return IdentidadeGoogle(subject=subject, email=email, nome=nome[:255])


def _campo_erro(resposta: httpx.Response) -> str | None:
    try:
        corpo = resposta.json()
    except ValueError:
        return None
    erro = corpo.get("error") if isinstance(corpo, dict) else None
    return erro if isinstance(erro, str) else None


@lru_cache
def get_google_provider() -> GoogleOAuthProvider:
    """Instância única (o cache de JWKS vive nela); testes sobrescrevem a dependência."""
    return GoogleOAuthProvider(get_settings())
