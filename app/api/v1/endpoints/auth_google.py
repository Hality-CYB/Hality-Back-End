"""Login com Google para paciente (US-012): authorize, callback e troca de código.

O navegador só passa por aqui em redirecionamentos: o `authorize` leva ao Google,
o Google devolve ao `callback` e o `callback` devolve ao frontend com um código
de troca de uso único (ou um código de erro). Nenhum token vai em query string:
a sessão só é emitida no `POST /exchange`, no mesmo formato do login por senha.
"""

from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi_users.authentication.strategy import DatabaseStrategy, JWTStrategy

from app.api.deps import DbSession, SettingsDep
from app.api.v1.endpoints.auth import AccessTokenResponse, emitir_sessao
from app.auth.google import GoogleOAuthProvider, get_google_provider
from app.auth.policies import CORRELATION_HEADER, definir_correlation_id
from app.auth.users import get_jwt_strategy, get_refresh_strategy
from app.core.config import Settings
from app.schemas.oauth_google import TrocaGoogleRequest
from app.services import consentimento_service, oauth_google_service
from app.services.identity_token_service import consume_rate_limit

router = APIRouter(prefix="/auth/google", tags=["auth"])

STATE_COOKIE_NAME = "google_oauth_state"
STATE_COOKIE_MAX_AGE = int(oauth_google_service.STATE_TTL.total_seconds())

ProviderDep = Annotated[GoogleOAuthProvider, Depends(get_google_provider)]


def _exigir_configurado(settings: Settings) -> None:
    if not settings.google_configurado:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="login com Google não configurado",
        )


def _cookie_path(settings: Settings) -> str:
    return f"{settings.api_v1_prefix}/auth/google"


def _redirecionar_ao_frontend(settings: Settings, parametros: dict[str, str]) -> RedirectResponse:
    base = urlparse(settings.google_frontend_redirect_url or "")
    consulta = dict(parse_qsl(base.query)) | parametros
    destino = urlunparse(base._replace(query=urlencode(consulta)))
    # 303: o destino é sempre GET. A URL carrega o código de troca, então não pode
    # ser cacheada nem vazar por Referer.
    return RedirectResponse(
        destino,
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


async def _limitar_authorize(request: Request, db: DbSession, settings: Settings) -> None:
    """O `authorize` é público e grava um fluxo por chamada: limita por IP do cliente."""
    client_host = request.client.host if request.client else "unknown"
    excedeu = await consume_rate_limit(
        db,
        f"google_authorize:{client_host}",
        limit=settings.google_authorize_rate_limit,
        window_seconds=settings.google_authorize_rate_window_seconds,
    )
    if excedeu:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="muitas tentativas de login com Google; aguarde e tente novamente",
            headers={"Retry-After": str(settings.google_authorize_rate_window_seconds)},
        )


@router.get("/authorize", name="auth:google_authorize")
async def authorize(
    request: Request, db: DbSession, settings: SettingsDep, provider: ProviderDep
) -> RedirectResponse:
    """Inicia o OAuth: redireciona o navegador ao Google (state, nonce e PKCE S256)."""
    _exigir_configurado(settings)
    await _limitar_authorize(request, db, settings)
    url, state = await oauth_google_service.iniciar_autorizacao(db, provider)

    resposta = RedirectResponse(
        url,
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Cache-Control": "no-store"},
    )
    resposta.set_cookie(
        key=STATE_COOKIE_NAME,
        value=state,
        max_age=STATE_COOKIE_MAX_AGE,
        path=_cookie_path(settings),
        httponly=True,
        secure=settings.environment == "production",
        # Lax: o cookie acompanha o redirecionamento GET que volta do Google.
        samesite="lax",
    )
    return resposta


@router.get("/callback", name="auth:google_callback")
async def callback(
    request: Request,
    db: DbSession,
    settings: SettingsDep,
    provider: ProviderDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Recebe o retorno do Google e devolve o navegador ao frontend (nunca JSON, nunca token)."""
    _exigir_configurado(settings)
    definir_correlation_id(request.headers.get(CORRELATION_HEADER))

    resultado = await oauth_google_service.processar_callback(
        db,
        provider,
        state=state,
        state_cookie=request.cookies.get(STATE_COOKIE_NAME),
        code=code,
        error=error,
    )

    if resultado.erro is not None:
        resposta = _redirecionar_ao_frontend(settings, {"erro": resultado.erro.value})
    else:
        resposta = _redirecionar_ao_frontend(
            settings, {"code": resultado.codigo or "", "etapa": resultado.etapa.value}
        )
    # O state é de uso único: o cookie sai em qualquer desfecho.
    resposta.delete_cookie(STATE_COOKIE_NAME, path=_cookie_path(settings))
    return resposta


@router.post("/exchange", response_model=AccessTokenResponse, name="auth:google_exchange")
async def exchange(
    dados: TrocaGoogleRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    jwt_strategy: Annotated[JWTStrategy, Depends(get_jwt_strategy)],
    refresh_strategy: Annotated[DatabaseStrategy, Depends(get_refresh_strategy)],
) -> AccessTokenResponse:
    """Troca o código de uso único por sessão (mesmo formato do login por senha).

    Conta nova (`etapa=consentimento`): exige o aceite do tratamento de dados de
    saúde em `consentimentos`; só então a conta é criada.
    """
    _exigir_configurado(settings)
    try:
        usuario = await oauth_google_service.trocar_codigo(
            db,
            codigo=dados.codigo,
            consentimentos=dados.consentimentos,
            referencia_coleta=definir_correlation_id(request.headers.get(CORRELATION_HEADER)),
        )

    except oauth_google_service.CodigoTrocaInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="código inválido, expirado ou já utilizado",
        ) from exc

    except consentimento_service.TratamentoObrigatorioError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="o consentimento para tratamento de dados de saúde é obrigatório",
        ) from exc

    except consentimento_service.DecisaoDuplicadaError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="finalidade de consentimento repetida",
        ) from exc

    except consentimento_service.VersaoDesatualizadaError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"versão do termo desatualizada; versão vigente: {exc.versao_vigente}",
        ) from exc

    except oauth_google_service.ContaExistenteError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="já existe uma conta com este e-mail",
        ) from exc

    except oauth_google_service.PapelNaoPermitidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="login com Google disponível apenas para pacientes",
        ) from exc

    except oauth_google_service.ContaInativaError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="conta inativa") from exc

    return await emitir_sessao(usuario, response, jwt_strategy, refresh_strategy)
