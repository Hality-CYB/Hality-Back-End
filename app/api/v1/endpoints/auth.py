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

from app.auth.users import UserManager, get_jwt_strategy, get_refresh_strategy, get_user_manager
from app.core.config import get_settings
from app.models.user import User

router = APIRouter()

REFRESH_COOKIE_NAME = "refresh_token"
# Só é enviado pelo navegador em chamadas dentro deste path — nunca em
# /anamneses, /diagnosticos, /users/me etc.
REFRESH_COOKIE_PATH = "/api/v1/auth"


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


async def _emitir_access_e_setar_cookie(
    user: User,
    response: Response,
    jwt_strategy: JWTStrategy,
    refresh_strategy: DatabaseStrategy,
) -> AccessTokenResponse:
    access_token = await jwt_strategy.write_token(user)
    refresh_token = await refresh_strategy.write_token(user)
    _definir_cookie_refresh(response, refresh_token)
    return AccessTokenResponse(access_token=access_token)


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
    return await _emitir_access_e_setar_cookie(user, response, jwt_strategy, refresh_strategy)


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
    if user is None or not user.is_active:
        _limpar_cookie_refresh(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="INVALID_REFRESH_TOKEN")

    # Rotação: o cookie usado morre aqui. Se o mesmo valor for reapresentado
    # depois (ex.: um atacante que roubou uma cópia antiga), a checagem
    # acima já vai falhar — sinal de comprometimento, não só de expiração.
    await refresh_strategy.destroy_token(refresh_token, user)
    return await _emitir_access_e_setar_cookie(user, response, jwt_strategy, refresh_strategy)


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
