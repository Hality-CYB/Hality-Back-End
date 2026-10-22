"""Login com Google para paciente (US-012 / TASK-107) — SQLite em memória.

O Google é simulado por um provider falso que só substitui a chamada de rede
(`obter_identidade`); URL de autorização, state, cookie, PKCE, fluxo e contas
são os reais. A validação do ID token tem testes próprios em
`tests/unit/test_google_provider.py`.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google import (
    CodigoRejeitadoError,
    EmailNaoVerificadoError,
    GoogleOAuthProvider,
    IdentidadeGoogle,
    IdTokenInvalidoError,
    ProvedorIndisponivelError,
    code_challenge_s256,
    get_google_provider,
)
from app.core.config import Settings, get_settings
from app.main import app
from app.models import (
    AuditoriaAcesso,
    ConsentimentoEvento,
    IdentidadeExterna,
    IdentityRateLimit,
    OAuthFluxo,
    User,
)
from tests.conftest import CONSENTIMENTOS_CADASTRO

AUTHORIZE_URL = "/api/v1/auth/google/authorize"
CALLBACK_URL = "/api/v1/auth/google/callback"
EXCHANGE_URL = "/api/v1/auth/google/exchange"
ME_URL = "/api/v1/users/me"
FRONTEND_URL = "http://localhost:3000/login/google"
CLIENT_SECRET = "segredo-do-cliente-jamais-no-frontend"

TRATAMENTO = {"finalidade": "health_data", "versao": "v1", "aceito": True}
TREINO_ACEITO = {"finalidade": "image_training", "versao": "v1", "aceito": True}
TREINO_RECUSADO = {"finalidade": "image_training", "versao": "v1", "aceito": False}

GOOGLE = IdentidadeGoogle(subject="sub-123", email="maria.google@gmail.com", nome="Maria Google")


class ProviderFalso(GoogleOAuthProvider):
    """Mantém a URL de autorização real; só a chamada ao Google é simulada."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.identidade: IdentidadeGoogle = GOOGLE
        self.erro: Exception | None = None
        self.chamadas: list[dict] = []

    async def obter_identidade(self, *, code: str, code_verifier: str, nonce: str):
        self.chamadas.append({"code": code, "code_verifier": code_verifier, "nonce": nonce})
        if self.erro is not None:
            raise self.erro
        return self.identidade


def _settings(**extras) -> Settings:
    base = {
        "google_client_id": "cliente-teste.apps.googleusercontent.com",
        "google_client_secret": SecretStr(CLIENT_SECRET),
        "google_redirect_uri": "http://localhost:8000/api/v1/auth/google/callback",
        "google_frontend_redirect_url": FRONTEND_URL,
    }
    return get_settings().model_copy(update=base | extras)


@pytest_asyncio.fixture
async def google(client: AsyncClient) -> AsyncGenerator[ProviderFalso]:
    settings = _settings()
    provider = ProviderFalso(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_google_provider] = lambda: provider
    yield provider
    # O fixture `client` limpa os overrides ao terminar.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _consulta(resposta) -> dict[str, str]:
    assert resposta.status_code in (302, 303), resposta.text
    return {k: v[0] for k, v in parse_qs(urlparse(resposta.headers["location"]).query).items()}


async def _iniciar(client: AsyncClient) -> str:
    resposta = await client.get(AUTHORIZE_URL, follow_redirects=False)
    assert resposta.status_code == 303
    return _consulta(resposta)["state"]


async def _callback(client: AsyncClient, state: str | None, **extras):
    params = ({"state": state} if state is not None else {}) | extras
    return await client.get(CALLBACK_URL, params=params, follow_redirects=False)


async def _fluxo_ate_o_callback(client: AsyncClient, **extras) -> dict[str, str]:
    state = await _iniciar(client)
    resposta = await _callback(client, state, **({"code": "codigo-do-google"} | extras))
    return _consulta(resposta)


async def _trocar(client: AsyncClient, codigo: str, consentimentos: list[dict] | None = None):
    corpo: dict = {"codigo": codigo}
    if consentimentos is not None:
        corpo["consentimentos"] = consentimentos
    return await client.post(EXCHANGE_URL, json=corpo)


async def _primeiro_login(client: AsyncClient, consentimentos: list[dict] | None = None) -> dict:
    retorno = await _fluxo_ate_o_callback(client)
    assert retorno["etapa"] == "consentimento"
    resposta = await _trocar(client, retorno["code"], consentimentos or [TRATAMENTO])
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


async def _contar(db: AsyncSession, modelo, *filtros) -> int:
    return await db.scalar(select(func.count()).select_from(modelo).where(*filtros))


async def _usuario(db: AsyncSession, email: str) -> User | None:
    db.expire_all()
    return await db.scalar(select(User).where(func.lower(User.email) == email.lower()))


async def _registrar_com_senha(
    client: AsyncClient, db: AsyncSession, email: str, role: str | None = None
) -> None:
    resposta = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "SenhaSegura123!",
            "data_nascimento": "1990-01-01",
            "name": "Conta Existente",
            "consentimentos": CONSENTIMENTOS_CADASTRO,
        },
    )
    assert resposta.status_code == 201
    if role is not None:
        usuario = await _usuario(db, email)
        usuario.role = role
        await db.commit()


# ---------------------------------------------------------------------------
# AC-012 — authorize: state, PKCE e nenhum segredo no navegador
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorize_redireciona_com_state_nonce_e_pkce_sem_segredo(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    resposta = await client.get(AUTHORIZE_URL, follow_redirects=False)

    assert resposta.status_code == 303
    destino = urlparse(resposta.headers["location"])
    assert f"{destino.scheme}://{destino.netloc}{destino.path}" == (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )
    consulta = _consulta(resposta)
    assert consulta["response_type"] == "code"
    assert consulta["code_challenge_method"] == "S256"
    assert consulta["client_id"] == "cliente-teste.apps.googleusercontent.com"
    assert consulta["redirect_uri"].endswith("/api/v1/auth/google/callback")
    assert CLIENT_SECRET not in resposta.headers["location"]

    # O state vai para o cookie httpOnly; no banco só o hash. PKCE e nonce batem.
    fluxo = await db_session.scalar(select(OAuthFluxo))
    cookie = resposta.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert f"google_oauth_state={consulta['state']}" in resposta.headers["set-cookie"]
    assert fluxo.state_hash != consulta["state"] and len(fluxo.state_hash) == 64
    assert consulta["state"] not in (fluxo.state_hash, fluxo.nonce)
    assert consulta["nonce"] == fluxo.nonce
    assert consulta["code_challenge"] == code_challenge_s256(fluxo.code_verifier)
    assert fluxo.estado == "iniciado"


@pytest.mark.asyncio
async def test_cada_authorize_gera_state_nonce_e_verifier_novos(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    await _iniciar(client)
    await _iniciar(client)

    fluxos = list(await db_session.scalars(select(OAuthFluxo)))
    assert len(fluxos) == 2
    assert len({f.state_hash for f in fluxos}) == 2
    assert len({f.nonce for f in fluxos}) == 2
    assert len({f.code_verifier for f in fluxos}) == 2


@pytest.mark.asyncio
async def test_authorize_acima_do_limite_devolve_429_e_nao_cria_fluxo(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    settings = _settings(google_authorize_rate_limit=2)
    app.dependency_overrides[get_settings] = lambda: settings

    await _iniciar(client)
    await _iniciar(client)
    bloqueada = await client.get(AUTHORIZE_URL, follow_redirects=False)

    assert bloqueada.status_code == 429
    assert bloqueada.headers["retry-after"] == str(settings.google_authorize_rate_window_seconds)
    assert "set-cookie" not in bloqueada.headers
    assert await _contar(db_session, OAuthFluxo) == 2


@pytest.mark.asyncio
async def test_limite_do_authorize_e_por_cliente(
    client: AsyncClient, google: ProviderFalso
) -> None:
    settings = _settings(google_authorize_rate_limit=1)
    app.dependency_overrides[get_settings] = lambda: settings

    await _iniciar(client)
    assert (await client.get(AUTHORIZE_URL, follow_redirects=False)).status_code == 429

    outro_ip = ASGITransport(app=app, client=("203.0.113.7", 50000))
    async with AsyncClient(transport=outro_ip, base_url="http://test") as outro_cliente:
        assert (await outro_cliente.get(AUTHORIZE_URL, follow_redirects=False)).status_code == 303


@pytest.mark.asyncio
async def test_authorize_volta_a_responder_quando_a_janela_vence(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    settings = _settings(google_authorize_rate_limit=1)
    app.dependency_overrides[get_settings] = lambda: settings
    await _iniciar(client)
    assert (await client.get(AUTHORIZE_URL, follow_redirects=False)).status_code == 429

    vencida = datetime.now(UTC) - timedelta(
        seconds=settings.google_authorize_rate_window_seconds + 1
    )
    await db_session.execute(update(IdentityRateLimit).values(window_started_at=vencida))
    await db_session.commit()

    assert (await client.get(AUTHORIZE_URL, follow_redirects=False)).status_code == 303


@pytest.mark.asyncio
async def test_sem_configuracao_o_login_google_fica_desligado(client: AsyncClient) -> None:
    settings = _settings(google_client_secret=None)
    app.dependency_overrides[get_settings] = lambda: settings

    assert (await client.get(AUTHORIZE_URL, follow_redirects=False)).status_code == 503
    assert (await client.get(CALLBACK_URL, params={"state": "x"})).status_code == 503
    assert (await _trocar(client, "qualquer")).status_code == 503


# ---------------------------------------------------------------------------
# AC-015 — state inválido, callback repetido, cancelamento, erros do provedor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_sem_state_ou_sem_cookie_ou_com_state_desconhecido_e_recusado(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    state = await _iniciar(client)

    sem_state = _consulta(await _callback(client, None, code="c"))
    desconhecido = _consulta(await _callback(client, "state-que-nao-existe", code="c"))
    client.cookies.clear()
    sem_cookie = _consulta(await _callback(client, state, code="c"))

    assert sem_state == desconhecido == sem_cookie == {"erro": "estado_invalido"}
    assert google.chamadas == []  # o Google nem é consultado
    assert await _contar(db_session, User) == 0
    # O fluxo legítimo continua intacto (nada o consumiu).
    fluxo = await db_session.scalar(select(OAuthFluxo))
    assert fluxo.estado == "iniciado"


@pytest.mark.asyncio
async def test_callback_com_cookie_de_outro_navegador_e_recusado(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    # Login CSRF: o atacante inicia o fluxo e entrega o state da vítima, que tem
    # outro cookie (ou nenhum). O state da URL sozinho não vale.
    state_do_atacante = await _iniciar(client)
    client.cookies.clear()
    client.cookies.set("google_oauth_state", "state-da-vitima", path="/api/v1/auth/google")

    retorno = _consulta(await _callback(client, state_do_atacante, code="c"))

    assert retorno == {"erro": "estado_invalido"}
    assert google.chamadas == []
    assert await _contar(db_session, User) == 0


@pytest.mark.asyncio
async def test_callback_repetido_e_recusado_e_so_uma_conta_e_possivel(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    state = await _iniciar(client)
    primeiro = _consulta(await _callback(client, state, code="c1"))
    # Repetição (F5, replay): o cookie já saiu, e o fluxo já foi consumido.
    client.cookies.set("google_oauth_state", state, path="/api/v1/auth/google")
    repetido = _consulta(await _callback(client, state, code="c1"))

    assert primeiro["etapa"] == "consentimento"
    assert repetido == {"erro": "estado_invalido"}
    assert len(google.chamadas) == 1


@pytest.mark.asyncio
async def test_state_expirado_e_recusado(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    state = await _iniciar(client)
    await db_session.execute(
        update(OAuthFluxo).values(expira_em=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()

    assert _consulta(await _callback(client, state, code="c")) == {"erro": "estado_invalido"}
    assert google.chamadas == []


@pytest.mark.asyncio
async def test_cancelamento_no_google_volta_recuperavel_sem_criar_conta(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    state = await _iniciar(client)

    retorno = _consulta(await _callback(client, state, error="access_denied"))

    assert retorno == {"erro": "cancelado"}
    assert google.chamadas == []
    assert await _contar(db_session, User) == 0
    assert await _contar(db_session, IdentidadeExterna) == 0
    fluxo = await db_session.scalar(select(OAuthFluxo))
    assert (fluxo.estado, fluxo.motivo_falha) == ("falhou", "cancelado")


@pytest.mark.asyncio
async def test_erro_do_provedor_no_callback(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    state = await _iniciar(client)

    retorno = _consulta(await _callback(client, state, error="server_error"))

    assert retorno == {"erro": "erro_provedor"}
    assert await _contar(db_session, User) == 0


@pytest.mark.asyncio
async def test_callback_sem_code_e_invalido(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    state = await _iniciar(client)

    assert _consulta(await _callback(client, state)) == {"erro": "callback_invalido"}
    assert await _contar(db_session, User) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("erro", "esperado"),
    [
        (ProvedorIndisponivelError(), "provedor_indisponivel"),
        (CodigoRejeitadoError(), "callback_invalido"),
        (EmailNaoVerificadoError(), "email_nao_verificado"),
        (IdTokenInvalidoError(), "identidade_invalida"),
    ],
    ids=["indisponivel", "codigo_rejeitado", "email_nao_verificado", "token_invalido"],
)
async def test_falhas_na_troca_com_o_google_nao_criam_conta_parcial(
    client: AsyncClient,
    google: ProviderFalso,
    db_session: AsyncSession,
    erro: Exception,
    esperado: str,
) -> None:
    google.erro = erro

    retorno = await _fluxo_ate_o_callback(client)

    assert retorno == {"erro": esperado}
    assert await _contar(db_session, User) == 0
    assert await _contar(db_session, IdentidadeExterna) == 0
    assert await _contar(db_session, ConsentimentoEvento) == 0
    fluxo = await db_session.scalar(select(OAuthFluxo))
    assert fluxo.estado == "falhou" and fluxo.codigo_hash is None


@pytest.mark.asyncio
async def test_depois_de_uma_falha_o_usuario_consegue_tentar_de_novo(
    client: AsyncClient, google: ProviderFalso
) -> None:
    google.erro = ProvedorIndisponivelError()
    assert await _fluxo_ate_o_callback(client) == {"erro": "provedor_indisponivel"}

    google.erro = None
    retorno = await _fluxo_ate_o_callback(client)

    assert retorno["etapa"] == "consentimento" and retorno["code"]


# ---------------------------------------------------------------------------
# AC-013 — primeiro login: conta paciente só depois do consentimento
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_do_primeiro_login_nao_cria_conta_e_pede_consentimento(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    state = await _iniciar(client)

    resposta = await _callback(client, state, code="codigo-do-google")

    retorno = _consulta(resposta)
    assert set(retorno) == {"code", "etapa"}
    assert retorno["etapa"] == "consentimento"
    assert resposta.headers["location"].startswith(FRONTEND_URL + "?")
    assert await _contar(db_session, User) == 0  # nenhuma conta antes do consentimento
    # PKCE e nonce do fluxo é que foram enviados ao Google.
    fluxo = await db_session.scalar(select(OAuthFluxo))
    assert google.chamadas == [
        {
            "code": "codigo-do-google",
            "code_verifier": fluxo.code_verifier,
            "nonce": fluxo.nonce,
        }
    ]


@pytest.mark.asyncio
async def test_redirecionamento_nao_carrega_token_nem_segredo_e_nao_e_cacheavel(
    client: AsyncClient, google: ProviderFalso
) -> None:
    state = await _iniciar(client)

    resposta = await _callback(client, state, code="codigo-do-google")

    local = resposta.headers["location"].lower()
    for proibido in ("access_token", "id_token", "refresh_token", "secret", CLIENT_SECRET):
        assert proibido.lower() not in local
    assert resposta.headers["cache-control"] == "no-store"
    assert resposta.headers["referrer-policy"] == "no-referrer"
    assert "google_oauth_state=" in resposta.headers["set-cookie"]  # cookie do state expirado


@pytest.mark.asyncio
async def test_callback_ignora_destino_enviado_pelo_cliente(
    client: AsyncClient, google: ProviderFalso
) -> None:
    state = await _iniciar(client)

    resposta = await _callback(
        client,
        state,
        code="c",
        redirect_uri="https://evil.example.com",
        next="https://evil.example.com",
    )

    assert resposta.headers["location"].startswith(FRONTEND_URL + "?")
    assert "evil" not in resposta.headers["location"]


@pytest.mark.asyncio
async def test_troca_de_conta_nova_exige_o_aceite_do_tratamento(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    retorno = await _fluxo_ate_o_callback(client)

    sem_nada = await _trocar(client, retorno["code"])
    so_treino = await _trocar(client, retorno["code"], [TREINO_ACEITO])
    recusado = await _trocar(client, retorno["code"], [{**TRATAMENTO, "aceito": False}])
    versao_velha = await _trocar(client, retorno["code"], [{**TRATAMENTO, "versao": "v0"}])

    assert [sem_nada.status_code, so_treino.status_code, recusado.status_code] == [422, 422, 422]
    assert versao_velha.status_code == 409
    assert await _contar(db_session, User) == 0
    assert await _contar(db_session, ConsentimentoEvento) == 0
    # O código não foi gasto: a pessoa ainda pode aceitar e concluir.
    ok = await _trocar(client, retorno["code"], [TRATAMENTO])
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_troca_cria_paciente_identidade_e_consentimentos_na_mesma_operacao(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    sessao = await _primeiro_login(client, [TRATAMENTO, TREINO_RECUSADO])

    # Mesmo shape do login por senha: access_token no corpo, refresh só em cookie httpOnly.
    assert set(sessao) == {"access_token", "token_type"} and sessao["token_type"] == "bearer"
    set_cookie = [c for c in client.cookies.jar if c.name == "refresh_token"]
    assert set_cookie

    usuario = await _usuario(db_session, GOOGLE.email)
    assert usuario.role == "paciente" and usuario.is_active and usuario.is_verified
    assert usuario.name == "Maria Google"
    assert usuario.hashed_password  # conta sem senha utilizável, mas coluna preenchida

    identidade = await db_session.scalar(select(IdentidadeExterna))
    assert (identidade.user_id, identidade.provider, identidade.subject) == (
        usuario.id,
        "google",
        "sub-123",
    )

    eventos = list(await db_session.scalars(select(ConsentimentoEvento).order_by("id")))
    assert [(e.finalidade, e.aceito, e.origem) for e in eventos] == [
        ("health_data", True, "google"),
        ("image_training", False, "google"),
    ]
    assert all(e.titular_id == usuario.id and e.ator_id == usuario.id for e in eventos)

    # O access token funciona nas rotas protegidas.
    me = await client.get(ME_URL, headers={"Authorization": f"Bearer {sessao['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == GOOGLE.email

    # A conta não tem senha conhecida: login por senha não entra.
    senha = await client.post(
        "/api/v1/auth/login", data={"username": GOOGLE.email, "password": "SenhaSegura123!"}
    )
    assert senha.status_code == 400


@pytest.mark.asyncio
async def test_codigo_de_troca_so_vale_uma_vez(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    retorno = await _fluxo_ate_o_callback(client)
    primeira = await _trocar(client, retorno["code"], [TRATAMENTO])

    repetida = await _trocar(client, retorno["code"], [TRATAMENTO])

    assert primeira.status_code == 200
    assert repetida.status_code == 400
    assert await _contar(db_session, User) == 1
    assert await _contar(db_session, IdentidadeExterna) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("codigo", ["", "nao-existe", "x" * 5000])
async def test_codigo_de_troca_inexistente_e_recusado(
    client: AsyncClient, google: ProviderFalso, codigo: str
) -> None:
    resposta = await client.post(EXCHANGE_URL, json={"codigo": codigo or "x"})

    assert resposta.status_code in (400, 422)


@pytest.mark.asyncio
async def test_codigo_de_troca_expirado_e_recusado(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    retorno = await _fluxo_ate_o_callback(client)
    await db_session.execute(
        update(OAuthFluxo).values(codigo_expira_em=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()

    resposta = await _trocar(client, retorno["code"], [TRATAMENTO])

    assert resposta.status_code == 400
    assert await _contar(db_session, User) == 0


@pytest.mark.asyncio
async def test_troca_nao_aceita_campos_extras(client: AsyncClient, google: ProviderFalso) -> None:
    resposta = await client.post(
        EXCHANGE_URL, json={"codigo": "x", "papel": "admin", "consentimentos": []}
    )

    assert resposta.status_code == 422


@pytest.mark.asyncio
async def test_dados_do_perfil_nao_ficam_no_fluxo_depois_de_concluir(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    await _primeiro_login(client)

    fluxo = await db_session.scalar(select(OAuthFluxo))
    assert fluxo.estado == "concluido"
    assert fluxo.email is None and fluxo.nome is None


# ---------------------------------------------------------------------------
# Identidade já vinculada — segundo login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_segundo_login_com_identidade_vinculada_entra_sem_novo_consentimento(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    await _primeiro_login(client)
    client.cookies.clear()

    retorno = await _fluxo_ate_o_callback(client)
    assert retorno["etapa"] == "sessao"
    resposta = await _trocar(client, retorno["code"])

    assert resposta.status_code == 200
    assert await _contar(db_session, User) == 1
    assert await _contar(db_session, IdentidadeExterna) == 1
    assert await _contar(db_session, ConsentimentoEvento) == 1  # só o do primeiro login
    identidade = await db_session.scalar(select(IdentidadeExterna))
    await db_session.refresh(identidade)
    assert identidade.ultimo_login_em is not None


@pytest.mark.asyncio
async def test_vinculo_e_pelo_sub_e_nao_pelo_email(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    await _primeiro_login(client)
    client.cookies.clear()
    # O mesmo `sub` volta com outro e-mail: continua sendo a mesma conta.
    google.identidade = IdentidadeGoogle(
        subject=GOOGLE.subject, email="email.novo@gmail.com", nome="Outro Nome"
    )

    retorno = await _fluxo_ate_o_callback(client)
    resposta = await _trocar(client, retorno["code"])

    assert retorno["etapa"] == "sessao" and resposta.status_code == 200
    assert await _contar(db_session, User) == 1
    assert (await _usuario(db_session, GOOGLE.email)) is not None
    assert (await _usuario(db_session, "email.novo@gmail.com")) is None


@pytest.mark.asyncio
async def test_outro_sub_com_o_mesmo_email_nao_assume_a_conta(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    await _primeiro_login(client)
    client.cookies.clear()
    google.identidade = IdentidadeGoogle(
        subject="sub-de-outra-pessoa", email=GOOGLE.email, nome="X Y"
    )

    retorno = await _fluxo_ate_o_callback(client)

    assert retorno == {"erro": "conta_existente"}
    assert await _contar(db_session, IdentidadeExterna) == 1


# ---------------------------------------------------------------------------
# AC-014 — sem vínculo silencioso por e-mail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conta_existente_com_mesmo_email_nao_e_vinculada(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    await _registrar_com_senha(client, db_session, "Maria.Google@Gmail.com")
    antes = await _usuario(db_session, GOOGLE.email)
    senha_antes = antes.hashed_password

    retorno = await _fluxo_ate_o_callback(client)

    assert retorno == {"erro": "conta_existente"}
    assert await _contar(db_session, IdentidadeExterna) == 0
    assert await _contar(db_session, User) == 1
    depois = await _usuario(db_session, GOOGLE.email)
    assert depois.id == antes.id and depois.hashed_password == senha_antes
    # E a conta segue acessível pela senha de sempre.
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "Maria.Google@Gmail.com", "password": "SenhaSegura123!"},
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_email_cadastrado_entre_o_callback_e_a_troca_nao_cria_duplicata(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    retorno = await _fluxo_ate_o_callback(client)
    await _registrar_com_senha(client, db_session, GOOGLE.email)

    resposta = await _trocar(client, retorno["code"], [TRATAMENTO])

    assert resposta.status_code == 409
    assert await _contar(db_session, User) == 1
    assert await _contar(db_session, IdentidadeExterna) == 0


# ---------------------------------------------------------------------------
# AC-016 — profissional e admin não entram pelo Google
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("papel", ["profissional", "admin"])
async def test_email_de_profissional_ou_admin_nao_entra_pelo_google(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession, papel: str
) -> None:
    await _registrar_com_senha(client, db_session, GOOGLE.email, role=papel)

    retorno = await _fluxo_ate_o_callback(client)

    assert retorno == {"erro": "papel_nao_permitido"}
    assert await _contar(db_session, IdentidadeExterna) == 0
    assert (await _usuario(db_session, GOOGLE.email)).role == papel


@pytest.mark.asyncio
@pytest.mark.parametrize("papel", ["profissional", "admin"])
async def test_identidade_vinculada_a_conta_que_nao_e_paciente_e_barrada(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession, papel: str
) -> None:
    await _primeiro_login(client)
    client.cookies.clear()
    usuario = await _usuario(db_session, GOOGLE.email)
    usuario.role = papel
    await db_session.commit()

    retorno = await _fluxo_ate_o_callback(client)

    assert retorno == {"erro": "papel_nao_permitido"}


@pytest.mark.asyncio
async def test_papel_alterado_entre_o_callback_e_a_troca_e_barrado_na_troca(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    await _primeiro_login(client)
    client.cookies.clear()
    retorno = await _fluxo_ate_o_callback(client)
    usuario = await _usuario(db_session, GOOGLE.email)
    usuario.role = "admin"
    await db_session.commit()

    resposta = await _trocar(client, retorno["code"])

    assert resposta.status_code == 403
    assert "access_token" not in resposta.text
    # O código foi queimado.
    assert (await _trocar(client, retorno["code"])).status_code == 400


@pytest.mark.asyncio
async def test_conta_inativa_nao_entra_pelo_google(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    await _primeiro_login(client)
    client.cookies.clear()
    usuario = await _usuario(db_session, GOOGLE.email)
    usuario.is_active = False
    await db_session.commit()

    assert await _fluxo_ate_o_callback(client) == {"erro": "conta_inativa"}


# ---------------------------------------------------------------------------
# Auditoria — tentativas e falhas, sem token nem perfil
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tentativas_e_falhas_sao_auditadas_sem_dados_sensiveis(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    google.erro = EmailNaoVerificadoError()
    await _fluxo_ate_o_callback(client)  # falha
    google.erro = None
    await _primeiro_login(client)  # sucesso
    await _callback(client, "state-forjado", code="c")  # estado inválido

    usuario = await _usuario(db_session, GOOGLE.email)
    linhas = list(
        await db_session.scalars(
            select(AuditoriaAcesso)
            .where(AuditoriaAcesso.acao.like("auth.google.%"))
            .order_by(AuditoriaAcesso.id)
        )
    )

    resumo = [
        (linha.acao, linha.resultado, (linha.metadados or {}).get("motivo")) for linha in linhas
    ]
    assert ("auth.google.autorizar", "sucesso", None) in resumo
    assert ("auth.google.callback", "falha", "email_nao_verificado") in resumo
    assert ("auth.google.callback", "falha", "estado_invalido") in resumo
    assert ("auth.google.callback", "sucesso", None) in resumo
    assert ("auth.google.trocar", "sucesso", None) in resumo
    troca = next(x for x in linhas if x.acao == "auth.google.trocar")
    assert troca.ator_id == usuario.id and troca.papel == "paciente"

    texto = " ".join(str(linha.metadados) + linha.recurso_id for linha in linhas).lower()
    for proibido in (GOOGLE.email, GOOGLE.subject, "codigo-do-google", CLIENT_SECRET, "token"):
        assert proibido.lower() not in texto


@pytest.mark.asyncio
async def test_codigo_de_troca_invalido_e_auditado(
    client: AsyncClient, google: ProviderFalso, db_session: AsyncSession
) -> None:
    await _trocar(client, "codigo-inexistente", [TRATAMENTO])

    linha = await db_session.scalar(
        select(AuditoriaAcesso).where(AuditoriaAcesso.acao == "auth.google.trocar")
    )
    assert linha.resultado == "falha" and linha.metadados["motivo"] == "codigo_invalido"
    assert "codigo-inexistente" not in str(linha.metadados) + linha.recurso_id
