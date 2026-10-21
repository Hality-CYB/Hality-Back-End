from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classificacao_diagnostico import ClassificacaoDiagnostico


async def listar(db: AsyncSession) -> list[ClassificacaoDiagnostico]:
    resultado = await db.execute(
        select(ClassificacaoDiagnostico).order_by(ClassificacaoDiagnostico.ordem.asc())
    )

    return list(resultado.scalars().all())
