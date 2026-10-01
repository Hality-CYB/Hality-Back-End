"""Dependências reutilizáveis via Depends (settings, sessão de banco, usuário autenticado)."""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.policies import (
    CORRELATION_HEADER,
    definir_correlation_id,
    normalizar_papel,
    registrar_decisao,
)
from app.auth.users import current_active_user, current_active_user_opcional
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.usuario import TipoUsuario

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db)]

# Alias para compatibilidade com código legado
DbDep = DbSession

LIMITE_MAXIMO_PAGINA = 50
PaginaQuery = Annotated[int, Query(ge=1)]
LimiteQuery = Annotated[int, Query(ge=1, le=LIMITE_MAXIMO_PAGINA)]

# Usuário autenticado e ativo injetado via JWT (fastapi-users). Inativo -> 401,
# antes de qualquer regra de papel ou de recurso.
CurrentUser = Annotated[User, Depends(current_active_user)]


def exigir_papeis(*papeis: TipoUsuario, opcional: bool = False) -> Callable[..., User | None]:
    """Cria uma dependência que só deixa passar usuários com um dos ``papeis``.

    Papel fora da lista (ou desconhecido) -> 403. Ver convenções 401/403/404 em
    ``app/auth/policies.py``. Com ``opcional=True``, request sem usuário
    autenticado devolve ``None`` em vez de 401 — a rota precisa então decidir
    por outra via (ex.: URL assinada) e responder 401 se não houver nenhuma.
    """
    permitidos = frozenset(papeis)
    obter_usuario = current_active_user_opcional if opcional else current_active_user

    # `async` de propósito: roda no mesmo contexto da request, então o correlation
    # id definido aqui chega aos logs de `pode_acessar_paciente` nos services.
    # (Dependência síncrona roda em thread separada e o ContextVar se perderia.)
    async def dependencia(
        user: Annotated[User | None, Depends(obter_usuario)], request: Request
    ) -> User | None:
        definir_correlation_id(request.headers.get(CORRELATION_HEADER))

        if user is None:
            return None

        if normalizar_papel(user.role) not in permitidos:
            # Só a rota (método + path); query string e corpo nunca vão para o log.
            registrar_decisao(
                permitido=False,
                motivo="papel_insuficiente",
                recurso=f"{request.method} {request.url.path}",
                usuario=user,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="papel sem permissão para esta operação",
            )
        return user

    # Marca a dependência para auditoria (tests/test_autorizacao.py verifica que
    # toda rota clínica declara papéis por aqui).
    dependencia.papeis_permitidos = permitidos  # type: ignore[attr-defined]
    return dependencia


CurrentPatient = Annotated[User, Depends(exigir_papeis(TipoUsuario.PACIENTE))]
CurrentProfessional = Annotated[User, Depends(exigir_papeis(TipoUsuario.PROFISSIONAL))]
CurrentAdmin = Annotated[User, Depends(exigir_papeis(TipoUsuario.ADMIN))]

# Leitura clínica: paciente (dados próprios) ou profissional (pacientes vinculados).
# O acesso ao recurso em si é decidido por `pode_acessar_paciente`.
CurrentClinicalUser = Annotated[
    User, Depends(exigir_papeis(TipoUsuario.PACIENTE, TipoUsuario.PROFISSIONAL))
]
# Mesma regra, mas sem 401 automático quando não há usuário (ver `exigir_papeis`).
OptionalClinicalUser = Annotated[
    User | None,
    Depends(exigir_papeis(TipoUsuario.PACIENTE, TipoUsuario.PROFISSIONAL, opcional=True)),
]


def get_current_patient_id(user: CurrentPatient) -> uuid.UUID:
    """Retorna o id do paciente autenticado; outros papéis recebem 403."""
    return user.id


CurrentPatientDep = Annotated[uuid.UUID, Depends(get_current_patient_id)]


def require_admin(user: CurrentUser) -> User:
    """Exige usuário autenticado com `role == "admin"`.

    401 (sem token/token inválido) vem do fastapi-users; aqui só tratamos o 403
    para quem está autenticado mas não é administrador.
    """
    if user.role != TipoUsuario.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="acesso restrito a administradores",
        )
    return user


CurrentAdminDep = Annotated[User, Depends(require_admin)]


def get_current_professional(user: CurrentUser) -> User:
    """Garante que o usuário autenticado tem papel de profissional."""
    if user.role != "profissional":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="acesso restrito a profissionais",
        )

    return user


CurrentProfessionalDep = Annotated[User, Depends(get_current_professional)]
