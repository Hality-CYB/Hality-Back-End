import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auditoria_acesso import AuditoriaAcesso

_CHAVES_SENSIVEIS = {
    "senha",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "url",
    "url_assinada",
    "imagem",
    "anamnese",
    "respostas",
    "payload",
    "conteudo",
}


class ChaveOperacaoReutilizadaError(Exception):
    """A chave já representa uma operação concluída ou incompatível."""


def _metadados_minimos(valor: Mapping[str, Any]) -> dict[str, Any]:
    """Mantém somente metadados pequenos e não sensíveis da operação."""
    resultado: dict[str, Any] = {}
    for chave, item in valor.items():
        chave_normalizada = chave.lower()
        if any(sensivel in chave_normalizada for sensivel in _CHAVES_SENSIVEIS):
            continue
        if isinstance(item, Mapping):
            resultado[chave] = _metadados_minimos(item)
        elif isinstance(item, list) and all(isinstance(elemento, str) for elemento in item):
            resultado[chave] = [elemento[:100] for elemento in item[:50]]
        elif isinstance(item, (str, int, float, bool)) or item is None:
            resultado[chave] = item
    return resultado


async def _registrar(
    session: AsyncSession,
    *,
    actor: Any,
    action: str,
    resource: str,
    resource_id: str | int,
    result: str,
    metadata: Mapping[str, Any] | None,
    operation_key: str | None,
) -> AuditoriaAcesso:
    if operation_key is not None:
        existente = await session.scalar(
            select(AuditoriaAcesso).where(AuditoriaAcesso.chave_operacao == operation_key)
        )
        if existente is not None:
            _validar_reutilizacao(existente, actor, action, resource, resource_id)
            raise ChaveOperacaoReutilizadaError(operation_key)

    registro = AuditoriaAcesso(
        ator_id=getattr(actor, "id", actor),
        papel=getattr(actor, "role", None),
        acao=action,
        recurso_tipo=resource,
        recurso_id=str(resource_id),
        resultado=result,
        metadados=_metadados_minimos(metadata or {}),
        chave_operacao=operation_key,
    )
    session.add(registro)
    try:
        await session.flush()
    except IntegrityError as exc:
        if operation_key is None or not _eh_colisao_chave_operacao(exc):
            raise
        await session.rollback()
        raise ChaveOperacaoReutilizadaError(operation_key) from exc
    return registro


async def validar_chave_operacao(
    session: AsyncSession,
    *,
    actor: Any,
    action: str,
    resource: str,
    resource_id: str | int,
    operation_key: str | None,
) -> None:
    """Valida a chave antes da mutação para impedir alterações sem novo evento."""
    if operation_key is None:
        return
    existente = await session.scalar(
        select(AuditoriaAcesso).where(AuditoriaAcesso.chave_operacao == operation_key)
    )
    if existente is not None:
        _validar_reutilizacao(existente, actor, action, resource, resource_id)
        raise ChaveOperacaoReutilizadaError(operation_key)


def _validar_reutilizacao(
    existente: AuditoriaAcesso,
    actor: Any,
    action: str,
    resource: str,
    resource_id: str | int,
) -> None:
    if (
        existente.ator_id != getattr(actor, "id", actor)
        or existente.acao != action
        or existente.recurso_tipo != resource
        or (resource_id != "novo" and existente.recurso_id != str(resource_id))
    ):
        raise ChaveOperacaoReutilizadaError("chave incompatível")


def _eh_colisao_chave_operacao(exc: IntegrityError) -> bool:
    atual: BaseException | None = exc.orig
    visitadas: set[int] = set()
    while atual is not None and id(atual) not in visitadas:
        visitadas.add(id(atual))
        sqlstate = getattr(atual, "sqlstate", None) or getattr(atual, "pgcode", None)
        diagnostico = getattr(atual, "diag", None)
        constraint_name = getattr(atual, "constraint_name", None) or getattr(
            diagnostico, "constraint_name", None
        )
        if sqlstate == "23505" and constraint_name == "uq_auditoria_acessos_chave_operacao":
            return True
        atual = getattr(atual, "__cause__", None) or getattr(atual, "__context__", None)
    return False


async def registrar_acesso(
    session: AsyncSession,
    actor: Any = None,
    action: str = "",
    resource: str = "",
    resource_id: int | str = "",
    *,
    ator_id: uuid.UUID | None = None,
    acao: str | None = None,
    recurso_tipo: str | None = None,
    recurso_id: int | str | None = None,
    result: str = "sucesso",
    metadata: Mapping[str, Any] | None = None,
    operation_key: str | None = None,
) -> AuditoriaAcesso:
    """Registra leitura na sessão ativa; o chamador controla o commit."""
    return await _registrar(
        session,
        actor=actor if actor is not None else ator_id,
        action=action or acao or "",
        resource=resource or recurso_tipo or "",
        resource_id=resource_id if recurso_id is None else recurso_id,
        result=result,
        metadata=metadata,
        operation_key=operation_key,
    )


async def registrar_mutacao(
    session: AsyncSession,
    actor: Any,
    action: str,
    resource: str,
    resource_id: int | str,
    metadata: Mapping[str, Any] | None = None,
    operation_key: str | None = None,
    result: str = "sucesso",
) -> AuditoriaAcesso:
    """Registra mutação na mesma transação da alteração de domínio."""
    return await _registrar(
        session,
        actor=actor,
        action=action,
        resource=resource,
        resource_id=resource_id,
        result=result,
        metadata=metadata,
        operation_key=operation_key,
    )
