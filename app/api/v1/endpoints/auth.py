"""Login/refresh/logout customizados — access JWT curto + refresh opaco.

O refresh_token nunca aparece no corpo da resposta nem em `localStorage`:
vive só num cookie `httpOnly` com `path` restrito às próprias rotas de auth
(o navegador nem anexa esse cookie em `/anamneses`, `/users/me` etc.), então
um XSS na SPA não tem como lê-lo via `document.cookie`/`localStorage` —
mesmo roubando o access_token (JWT, curto), não consegue se perpetuar.

Substitui o `fastapi_users.get_auth_router()` (que só sabe emitir o token de
uma única strategy, e não sabe lidar com cookie) por rotas finas que usam os
mesmos mecanismos da lib por baixo: `UserManager.authenticate()` para validar
credenciais e as duas strategies (`get_jwt_strategy`, `get_refresh_strategy`)
para emitir/validar os tokens.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users.authentication.strategy import DatabaseStrategy, JWTStrategy
from fastapi_users.router.common import ErrorCode
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession
from app.auth.policies import CORRELATION_HEADER, definir_correlation_id
from app.auth.users import UserManager, get_jwt_strategy, get_refresh_strategy, get_user_manager
from app.core.config import get_settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.identity import (
    EmailVerificationConfirm,
    EmailVerificationResend,
    EmailVerificationResendResponse,
    InvitationConfirmRequest,
    PasswordRecoveryConfirm,
    PasswordRecoveryRequest,
    PasswordRecoveryResponse,
)
from app.schemas.user import RegistroCreate, UserRead
from app.services import consentimento_service, registro_service
from app.services.identity_token_service import (
    InvalidIdentityTokenError,
    confirm_email_verification,
    consume_email_verification_rate_limit,
    consume_invitation,
    consume_password_reset,
    consume_recovery_rate_limit,
    request_email_verification_resend,
    request_password_recovery,
)

router = APIRouter()

REFRESH_COOKIE_NAME = "refresh_token"
# Só é enviado pelo navegador em chamadas dentro deste path — nunca em
# /anamneses, /diagnosticos, /users/me etc.
REFRESH_COOKIE_PATH = "/api/v1/auth"
PASSWORD_RECOVERY_MESSAGE = "Se o endereço estiver cadastrado, enviaremos instruções."
EMAIL_VERIFICATION_RESEND_MESSAGE = (
    "Se o endereço estiver cadastrado e pendente de confirmação, enviaremos um novo link."
)
EMAIL_NOT_VERIFIED = "EMAIL_NOT_VERIFIED"


class AccessTokenResponse(BaseModel):
    """Corpo de resposta de login/refresh — só o access_token vai aqui."""

    access_token: str
    token_type: str = "bearer"


def _definir_cookie_refresh(response: Response, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
    )


def _limpar_cookie_refresh(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


def _cabecalhos_sem_cookie_refresh() -> dict[str, str]:
    resposta = Response()
    _limpar_cookie_refresh(resposta)
    return {"set-cookie": resposta.headers["set-cookie"]}


async def emitir_sessao(
    user: User,
    response: Response,
    jwt_strategy: JWTStrategy,
    refresh_strategy: DatabaseStrategy,
) -> AccessTokenResponse:
    access_token = await jwt_strategy.write_token(user)
    refresh_token = await refresh_strategy.write_token(user)
    _definir_cookie_refresh(response, refresh_token)
    return AccessTokenResponse(access_token=access_token)


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    name="register:register",
)
async def register(
    dados: RegistroCreate,
    request: Request,
    db: DbSession,
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
) -> UserRead:
    """Cadastro de paciente. Exige o aceite do tratamento de dados de saúde (AC-021)."""
    try:
        usuario = await registro_service.registrar_paciente(
            db,
            dados,
            referencia_coleta=definir_correlation_id(request.headers.get(CORRELATION_HEADER)),
        )

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

    except registro_service.EmailJaCadastradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorCode.REGISTER_USER_ALREADY_EXISTS,
        ) from exc

    await user_manager.on_after_register(usuario, request)
    return UserRead.model_validate(usuario)


@router.post("/login", response_model=AccessTokenResponse, name="auth:login")
async def login(
    response: Response,
    credentials: Annotated[OAuth2PasswordRequestForm, Depends()],
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
    jwt_strategy: Annotated[JWTStrategy, Depends(get_jwt_strategy)],
    refresh_strategy: Annotated[DatabaseStrategy, Depends(get_refresh_strategy)],
) -> AccessTokenResponse:
    user = await user_manager.authenticate(credentials)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorCode.LOGIN_BAD_CREDENTIALS,
        )
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=EMAIL_NOT_VERIFIED,
            headers=_cabecalhos_sem_cookie_refresh(),
        )
    return await emitir_sessao(user, response, jwt_strategy, refresh_strategy)


@router.post("/refresh", response_model=AccessTokenResponse, name="auth:refresh")
async def refresh(
    request: Request,
    response: Response,
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
    jwt_strategy: Annotated[JWTStrategy, Depends(get_jwt_strategy)],
    refresh_strategy: Annotated[DatabaseStrategy, Depends(get_refresh_strategy)],
) -> AccessTokenResponse:
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="INVALID_REFRESH_TOKEN")

    user = await refresh_strategy.read_token(refresh_token, user_manager)
    if user is None or not user.is_active or not user.is_verified:
        if user is not None:
            await refresh_strategy.destroy_token(refresh_token, user)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_REFRESH_TOKEN",
            headers=_cabecalhos_sem_cookie_refresh(),
        )

    # Rotação: o cookie usado morre aqui. Se o mesmo valor for reapresentado
    # depois (ex.: um atacante que roubou uma cópia antiga), a checagem
    # acima já vai falhar — sinal de comprometimento, não só de expiração.
    await refresh_strategy.destroy_token(refresh_token, user)
    return await emitir_sessao(user, response, jwt_strategy, refresh_strategy)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, name="auth:logout")
async def logout(
    request: Request,
    response: Response,
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
    refresh_strategy: Annotated[DatabaseStrategy, Depends(get_refresh_strategy)],
) -> None:
    """Encerra a sessão de verdade: apaga o refresh_token do banco e do cookie.

    O access token (JWT) em uso continua tecnicamente válido até expirar
    sozinho (no máximo `access_token_expire_minutes`) — é o preço de manter
    o JWT stateless; o refresh, que é o que perpetuaria a sessão, morre aqui.
    """
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_token is not None:
        user = await refresh_strategy.read_token(refresh_token, user_manager)
        if user is not None:
            await refresh_strategy.destroy_token(refresh_token, user)
    _limpar_cookie_refresh(response)


@router.post(
    "/password-recovery",
    response_model=PasswordRecoveryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    name="auth:password-recovery",
)
async def password_recovery(
    payload: PasswordRecoveryRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PasswordRecoveryResponse:
    """Solicita recuperação sem revelar a existência do endereço."""
    client_host = request.client.host if request.client else "unknown"
    if not await consume_recovery_rate_limit(db, f"{client_host}:{payload.email}"):
        await request_password_recovery(db, str(payload.email))
    return PasswordRecoveryResponse(message=PASSWORD_RECOVERY_MESSAGE)


@router.post("/password-recovery/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def password_recovery_confirm(
    payload: PasswordRecoveryConfirm,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    try:
        await consume_password_reset(db, payload.token, payload.senha)
    except InvalidIdentityTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOKEN_DE_RECUPERACAO_INVALIDO",
        ) from exc


@router.post("/invitation/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def invitation_confirm(
    payload: InvitationConfirmRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    try:
        await consume_invitation(
            db,
            payload.token,
            payload.senha,
            consentimentos=payload.consentimentos,
            referencia_coleta=definir_correlation_id(request.headers.get(CORRELATION_HEADER)),
        )
    except InvalidIdentityTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOKEN_DE_CONVITE_INVALIDO",
        ) from exc
    # Mesmas respostas do `/auth/register`: sem isso as duas últimas viram 500.
    except consentimento_service.TratamentoObrigatorioError as exc:
        # Código estável (como TOKEN_DE_CONVITE_INVALIDO): o front mostra os termos ao
        # receber este código, sem depender do texto da mensagem.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="CONSENTIMENTO_OBRIGATORIO",
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


@router.post(
    "/email-verification/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    name="auth:email-verification-confirm",
)
async def email_verification_confirm(
    payload: EmailVerificationConfirm,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    try:
        await confirm_email_verification(db, payload.token)
    except InvalidIdentityTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOKEN_DE_VERIFICACAO_INVALIDO",
        ) from exc


@router.post(
    "/email-verification/resend",
    response_model=EmailVerificationResendResponse,
    status_code=status.HTTP_202_ACCEPTED,
    name="auth:email-verification-resend",
)
async def email_verification_resend(
    payload: EmailVerificationResend,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EmailVerificationResendResponse:
    client_host = request.client.host if request.client else "unknown"
    if not await consume_email_verification_rate_limit(db, f"{client_host}:{payload.email}"):
        await request_email_verification_resend(db, str(payload.email))
    return EmailVerificationResendResponse(message=EMAIL_VERIFICATION_RESEND_MESSAGE)
