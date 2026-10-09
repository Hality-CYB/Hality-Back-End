from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classificacao_diagnostico import ClassificacaoDiagnostico
from app.models.conteudo import Conteudo
from app.schemas.conteudo import CategoriaConteudo, OrdemConteudo, StatusConteudo


async def listar(
    db: AsyncSession,
    *,
    busca: str | None,
    status: StatusConteudo | None,
    categoria: CategoriaConteudo | None,
    classificacao_id: int | None,
    aparece_na_home: bool | None,
    page: int,
    limit: int,
    order: OrdemConteudo,
) -> tuple[list[Conteudo], int]:
    filtros = []
    if busca:
        filtros.append(Conteudo.titulo.icontains(busca, autoescape=True))
    if status is not None:
        filtros.append(Conteudo.status == status)
    if categoria is not None:
        filtros.append(Conteudo.categoria == categoria)
    if classificacao_id is not None:
        filtros.append(Conteudo.classificacao_ids.contains([classificacao_id]))
    if aparece_na_home is not None:
        filtros.append(Conteudo.aparece_na_home.is_(aparece_na_home))

    total = await db.scalar(select(func.count()).select_from(Conteudo).where(*filtros)) or 0
    if order == OrdemConteudo.ORDEM_DESC:
        ordenacao = (Conteudo.ordem.desc(), Conteudo.created_at.desc(), Conteudo.id.desc())
    elif order == OrdemConteudo.CRIADO_ASC:
        ordenacao = (Conteudo.created_at.asc(), Conteudo.ordem.asc(), Conteudo.id.asc())
    elif order == OrdemConteudo.CRIADO_DESC:
        ordenacao = (Conteudo.created_at.desc(), Conteudo.ordem.asc(), Conteudo.id.asc())
    else:
        ordenacao = (Conteudo.ordem.asc(), Conteudo.created_at.asc(), Conteudo.id.asc())

    resultado = await db.execute(
        select(Conteudo)
        .where(*filtros)
        .order_by(*ordenacao)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return list(resultado.scalars().all()), total


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
