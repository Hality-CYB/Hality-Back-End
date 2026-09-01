"""Endpoints de autenticação: registro de paciente, login e dados do usuário atual."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUserDep, DbDep
from app.core.security import create_access_token
from app.schemas.user import Token, UserLogin, UserRegister, UserResponse
from app.services.auth_service import authenticate_user, register_patient

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register-patient", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(user_in: UserRegister, db: DbDep) -> Token:
    """Cadastra um novo paciente e retorna um token JWT."""
    try:
        user = await register_patient(db, user_in)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    access_token = create_access_token(data={"sub": user.email})
    return Token(access_token=access_token)


@router.post("/login", response_model=Token)
async def login(credentials: UserLogin, db: DbDep) -> Token:
    """Autentica o usuário e retorna um token JWT."""
    user = await authenticate_user(db, credentials.email, credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.email})
    return Token(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUserDep) -> UserResponse:
    """Retorna os dados do usuário autenticado."""
    return UserResponse.model_validate(current_user)
