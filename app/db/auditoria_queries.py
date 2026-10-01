import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auditoria_acesso import AuditoriaAcesso


async def registrar_acesso(
    db: AsyncSession,
    ator_id: uuid.UUID,
    acao: str,
    recurso_tipo: str,
    recurso_id: int | str,
) -> AuditoriaAcesso:
    """Insere uma linha de auditoria e faz commit."""
    registro = AuditoriaAcesso(
        ator_id=ator_id,
        acao=acao,
        recurso_tipo=recurso_tipo,
        recurso_id=str(recurso_id),
    )

    db.add(registro)

    await db.commit()

    return registro
