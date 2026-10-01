import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Row, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classificacao_diagnostico import ClassificacaoDiagnostico
from app.models.diagnostico import Diagnostico
from app.models.paciente_profissional import PacienteProfissional
from app.models.user import User

ROLE_PACIENTE = "paciente"


@dataclass
class ResumoDiagnosticos:
    total: int
    ultimo_em: datetime | None
    ultimo_status: str | None
    ultimo_nivel: int | None


@dataclass
class PacientesPaginados:
    itens: list[Row]
    total: int


def _colunas_paciente() -> tuple:
    return (User.id, User.name, User.email, User.phone, User.is_active)


def _filtros_escopo(profissional_id: uuid.UUID | None) -> list:
    filtros = [User.role == ROLE_PACIENTE]

    if profissional_id is not None:
        filtros.append(
            exists().where(
                PacienteProfissional.paciente_id == User.id,
                PacienteProfissional.profissional_id == profissional_id,
                PacienteProfissional.ativo.is_(True),
            )
        )

    return filtros


def _escapar_like(valor: str) -> str:
    return valor.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def listar_pacientes(
    db: AsyncSession,
    profissional_id: uuid.UUID | None,
    busca: str | None,
    pagina: int,
    limite: int,
) -> PacientesPaginados:
    filtros = _filtros_escopo(profissional_id)

    if busca:
        padrao = f"%{_escapar_like(busca)}%"
        filtros.append(
            or_(
                User.name.ilike(padrao, escape="\\"),
                User.email.ilike(padrao, escape="\\"),
            )
        )

    total = await db.scalar(select(func.count()).select_from(User).where(*filtros))

    resultado = await db.execute(
        select(*_colunas_paciente())
        .where(*filtros)
        .order_by(func.lower(User.name).asc(), User.id.asc())
        .offset((pagina - 1) * limite)
        .limit(limite)
    )

    return PacientesPaginados(itens=list(resultado.all()), total=total or 0)


async def buscar_paciente(
    db: AsyncSession,
    paciente_id: uuid.UUID,
    profissional_id: uuid.UUID | None,
) -> Row | None:
    resultado = await db.execute(
        select(*_colunas_paciente()).where(
            User.id == paciente_id,
            *_filtros_escopo(profissional_id),
        )
    )

    return resultado.one_or_none()


async def resumir_diagnosticos(
    db: AsyncSession,
    paciente_ids: list[uuid.UUID],
) -> dict[uuid.UUID, ResumoDiagnosticos]:
    if not paciente_ids:
        return {}

    ranqueados = (
        select(
            Diagnostico.paciente_id,
            Diagnostico.data_diagnostico,
            Diagnostico.status,
            Diagnostico.classificacao_id,
            func.count().over(partition_by=Diagnostico.paciente_id).label("total"),
            func.row_number()
            .over(
                partition_by=Diagnostico.paciente_id,
                order_by=(Diagnostico.data_diagnostico.desc(), Diagnostico.id.desc()),
            )
            .label("posicao"),
        )
        .where(Diagnostico.paciente_id.in_(paciente_ids))
        .subquery()
    )

    resultado = await db.execute(
        select(
            ranqueados.c.paciente_id,
            ranqueados.c.total,
            ranqueados.c.data_diagnostico,
            ranqueados.c.status,
            ClassificacaoDiagnostico.ordem,
        )
        .outerjoin(
            ClassificacaoDiagnostico,
            ClassificacaoDiagnostico.id == ranqueados.c.classificacao_id,
        )
        .where(ranqueados.c.posicao == 1)
    )

    return {
        paciente_id: ResumoDiagnosticos(
            total=total,
            ultimo_em=data_diagnostico,
            ultimo_status=status,
            ultimo_nivel=ordem,
        )
        for paciente_id, total, data_diagnostico, status, ordem in resultado.all()
    }


async def listar_vinculos_do_paciente(
    db: AsyncSession,
    paciente_id: uuid.UUID,
    profissional_id: uuid.UUID | None,
) -> list[tuple[PacienteProfissional, str]]:
    filtros = [PacienteProfissional.paciente_id == paciente_id]

    if profissional_id is not None:
        filtros.append(PacienteProfissional.profissional_id == profissional_id)

    resultado = await db.execute(
        select(PacienteProfissional, User.name)
        .join(User, User.id == PacienteProfissional.profissional_id)
        .where(*filtros)
        .order_by(PacienteProfissional.data_vinculo.desc(), PacienteProfissional.id.desc())
    )

    return [(vinculo, nome) for vinculo, nome in resultado.all()]
