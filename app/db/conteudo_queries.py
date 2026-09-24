from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classificacao_diagnostico import ClassificacaoDiagnostico
from app.models.conteudo import Conteudo


async def listar(db: AsyncSession) -> list[Conteudo]:
    resultado = await db.execute(
        select(Conteudo).order_by(Conteudo.ordem.asc(), Conteudo.id.asc())
    )
    return list(resultado.scalars().all())


async def buscar_por_id(db: AsyncSession, conteudo_id: int) -> Conteudo | None:
    return await db.get(Conteudo, conteudo_id)


async def listar_classificacao_ids_existentes(
    db: AsyncSession, classificacao_ids: list[int]
) -> set[int]:
    if not classificacao_ids:
        return set()
    resultado = await db.execute(
        select(ClassificacaoDiagnostico.id).where(
            ClassificacaoDiagnostico.id.in_(classificacao_ids)
        )
    )
    return set(resultado.scalars().all())


async def inserir(db: AsyncSession, valores: dict) -> Conteudo:
    conteudo = Conteudo(**valores)
    db.add(conteudo)
    await db.commit()
    await db.refresh(conteudo)
    return conteudo


async def atualizar(db: AsyncSession, conteudo: Conteudo, valores: dict) -> Conteudo:
    for campo, valor in valores.items():
        setattr(conteudo, campo, valor)
    await db.commit()
    await db.refresh(conteudo)
    return conteudo


async def deletar(db: AsyncSession, conteudo: Conteudo) -> None:
    await db.delete(conteudo)
    await db.commit()
