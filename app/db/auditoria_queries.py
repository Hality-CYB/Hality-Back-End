import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
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


def _metadados_minimos(valor: Mapping[str, Any]) -> dict[str, Any]:
    """Mantém somente metadados pequenos e não sensíveis da operação."""
    resultado: dict[str, Any] = {}
    for chave, item in valor.items():
        chave_normalizada = chave.lower()
        if any(sensivel in chave_normalizada for sensivel in _CHAVES_SENSIVEIS):
            continue
        if isinstance(item, Mapping):
            resultado[chave] = _metadados_minimos(item)
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
            return existente

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
    await session.flush()
    return registro


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
