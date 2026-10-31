"""Login com Google contra o Postgres real (tipos, fuso, constraints e UPDATE condicional).

A lógica do fluxo está coberta em `test_auth_google.py` (SQLite); aqui o mesmo
caminho feliz, o callback repetido e o vínculo por `sub` rodam no banco de
verdade, com o Google simulado.
"""

import uuid
from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google import GoogleOAuthProvider, IdentidadeGoogle, get_google_provider
from app.core.config import get_settings
from app.main import app
from app.models import ConsentimentoEvento, IdentidadeExterna, OAuthFluxo, User
from tests.conftest import executar_no_banco

AUTHORIZE_URL = "/api/v1/auth/google/authorize"
CALLBACK_URL = "/api/v1/auth/google/callback"
EXCHANGE_URL = "/api/v1/auth/google/exchange"
FRONTEND_URL = "http://localhost:3000/login/google"
TRATAMENTO = {"finalidade": "health_data", "versao": "v1", "aceito": True}


class _ProviderFalso(GoogleOAuthProvider):
    def __init__(self, identidade: IdentidadeGoogle) -> None:
        super().__init__(_settings_google())
        self.identidade = identidade

    async def obter_identidade(self, *, code: str, code_verifier: str, nonce: str):
        return self.identidade


def _settings_google():
    return get_settings().model_copy(
        update={
            "google_client_id": "cliente-teste.apps.googleusercontent.com",
            "google_client_secret": SecretStr("segredo"),
            "google_redirect_uri": "http://localhost:8000/api/v1/auth/google/callback",
            "google_frontend_redirect_url": FRONTEND_URL,
            # O banco é persistente e o TestClient tem sempre o mesmo IP: sem folga,
            # execuções seguidas da suíte acumulariam tentativas na mesma janela.
            "google_authorize_rate_limit": 1000,
        }
    )


def _limpar(email: str, subject: str) -> None:
    async def _executar(db: AsyncSession) -> None:
        ids = select(User.id).where(User.email == email)
        await db.execute(delete(ConsentimentoEvento).where(ConsentimentoEvento.titular_id.in_(ids)))
        await db.execute(delete(OAuthFluxo).where(OAuthFluxo.subject == subject))
        await db.execute(delete(User).where(User.email == email))  # identidade sai em cascata
        await db.commit()

    executar_no_banco(_executar)


@pytest.fixture
def conta_google() -> Iterator[IdentidadeGoogle]:
    token = uuid.uuid4().hex
    identidade = IdentidadeGoogle(
        subject=f"sub-{token}", email=f"google.{token}@hality.com", nome="Paciente Google"
    )
    settings = _settings_google()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_google_provider] = lambda: _ProviderFalso(identidade)
    try:
        yield identidade
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_google_provider, None)
        _limpar(identidade.email, identidade.subject)


def _consulta(resposta) -> dict[str, str]:
    assert resposta.status_code == 303, resposta.text
    return {k: v[0] for k, v in parse_qs(urlparse(resposta.headers["location"]).query).items()}


def _ate_o_callback(client: TestClient) -> dict[str, str]:
    inicio = client.get(AUTHORIZE_URL, follow_redirects=False)
    state = _consulta(inicio)["state"]
    return _consulta(
        client.get(CALLBACK_URL, params={"state": state, "code": "c"}, follow_redirects=False)
    )


def _contagens(email: str) -> tuple[int, int, int]:
    async def _contar(db: AsyncSession) -> tuple[int, int, int]:
        usuarios = await db.scalar(
            select(func.count()).select_from(User).where(User.email == email)
        )
        identidades = await db.scalar(
            select(func.count())
            .select_from(IdentidadeExterna)
            .join(User, User.id == IdentidadeExterna.user_id)
            .where(User.email == email)
        )
        eventos = await db.scalar(
            select(func.count())
            .select_from(ConsentimentoEvento)
            .join(User, User.id == ConsentimentoEvento.titular_id)
            .where(User.email == email)
        )
        return usuarios, identidades, eventos

    return executar_no_banco(_contar)


def test_primeiro_login_google_cria_paciente_apos_consentimento(
    conta_google: IdentidadeGoogle,
) -> None:
    client = TestClient(app)

    retorno = _ate_o_callback(client)
    assert retorno["etapa"] == "consentimento"
    assert _contagens(conta_google.email) == (0, 0, 0)  # nenhuma conta antes do aceite

    sem_aceite = client.post(EXCHANGE_URL, json={"codigo": retorno["code"]})
    assert sem_aceite.status_code == 422
    assert _contagens(conta_google.email) == (0, 0, 0)

    sessao = client.post(
        EXCHANGE_URL, json={"codigo": retorno["code"], "consentimentos": [TRATAMENTO]}
    )
    assert sessao.status_code == 200
    assert set(sessao.json()) == {"access_token", "token_type"}
    assert _contagens(conta_google.email) == (1, 1, 1)

    repetida = client.post(
        EXCHANGE_URL, json={"codigo": retorno["code"], "consentimentos": [TRATAMENTO]}
    )
    assert repetida.status_code == 400

    me = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {sessao.json()['access_token']}"}
    )
    assert me.status_code == 200 and me.json()["role"] == "paciente"


def test_segundo_login_reutiliza_a_conta_vinculada_pelo_sub(
    conta_google: IdentidadeGoogle,
) -> None:
    client = TestClient(app)
    primeiro = _ate_o_callback(client)
    assert (
        client.post(
            EXCHANGE_URL, json={"codigo": primeiro["code"], "consentimentos": [TRATAMENTO]}
        ).status_code
        == 200
    )

    segundo = _ate_o_callback(TestClient(app))

    assert segundo["etapa"] == "sessao"
    resposta = TestClient(app).post(EXCHANGE_URL, json={"codigo": segundo["code"]})
    assert resposta.status_code == 200
    assert _contagens(conta_google.email) == (1, 1, 1)


def test_callback_repetido_no_postgres_e_recusado(conta_google: IdentidadeGoogle) -> None:
    client = TestClient(app)
    state = _consulta(client.get(AUTHORIZE_URL, follow_redirects=False))["state"]
    params = {"state": state, "code": "c"}

    primeiro = _consulta(client.get(CALLBACK_URL, params=params, follow_redirects=False))
    client.cookies.set("google_oauth_state", state, path="/api/v1/auth/google")
    repetido = _consulta(client.get(CALLBACK_URL, params=params, follow_redirects=False))

    assert primeiro["etapa"] == "consentimento"
    assert repetido == {"erro": "estado_invalido"}
