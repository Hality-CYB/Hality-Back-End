"""Endpoints de autenticação: registro, login, logout e perfil do usuário."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbDep
from app.core.security import create_access_token
from app.schemas.user import LoginRequest, Token, UserCreate, UserRead
from app.services.auth import authenticate_user, register_user

router = APIRouter()


@router.post(
    "/auth/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastrar novo usuário",
)
async def register(payload: UserCreate, session: DbDep) -> UserRead:
    """Cria uma nova conta de usuário.

    - **email**: deve ser único no sistema
    - **password**: mínimo 8 caracteres
    - **name**: nome completo (mínimo 2 caracteres)
    - **phone**: opcional
    """
    try:
        user = await register_user(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return UserRead.model_validate(user)


@router.post(
    "/auth/login",
    response_model=Token,
    summary="Autenticar usuário e obter token JWT",
)
async def login(payload: LoginRequest, session: DbDep) -> Token:
    """Autentica o usuário com e-mail e senha e retorna um token JWT Bearer.

    O token deve ser enviado no header ``Authorization: Bearer <token>``
    em todas as requisições a endpoints protegidos.
    """
    user = await authenticate_user(session, payload.email, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(subject=str(user.id))
    return Token(access_token=access_token)


@router.post(
    "/auth/logout",
    status_code=status.HTTP_200_OK,
    summary="Logout (stateless)",
)
async def logout(current_user: CurrentUser) -> dict[str, str]:
    """Endpoint de logout.

    Como os tokens JWT são stateless, o logout é gerenciado pelo cliente
    descartando o token. Este endpoint confirma a ação e pode ser estendido
    futuramente com uma blocklist (ex.: Redis).
    """
    return {"message": f"Usuário {current_user.email} desconectado com sucesso."}


@router.get(
    "/users/me",
    response_model=UserRead,
    summary="Obter dados do usuário autenticado",
)
async def get_me(current_user: CurrentUser) -> UserRead:
    """Retorna os dados do usuário autenticado pelo token Bearer."""
    return UserRead.model_validate(current_user)
