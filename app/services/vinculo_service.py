"""Criação, listagem e desvinculação do vínculo paciente-profissional (DEC-01).

DEC-01: o paciente se cadastra sozinho na plataforma (sem intervenção do
profissional). O profissional seleciona/"puxa" um paciente já cadastrado
pelo e-mail — não há convite, credencial de profissional ou consentimento
por vínculo (fora de escopo desta decisão).
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import paciente_profissional_queries as queries
from app.models.paciente_profissional import PacienteProfissional
from app.models.user import User
from app.schemas.paciente_profissional import VinculoDetail, VinculoListResponse


class PacienteNaoEncontradoError(Exception):
    pass


class PacienteInvalidoError(Exception):
    def __init__(self, motivo: str) -> None:
        self.motivo = motivo
        super().__init__(motivo)


class VinculoJaExisteError(Exception):
    pass


class VinculoNaoEncontradoError(Exception):
    pass


def _para_detalhe(vinculo: PacienteProfissional, paciente: User) -> VinculoDetail:
    return VinculoDetail(
        id=vinculo.id,
        paciente_id=vinculo.paciente_id,
        paciente_nome=paciente.name,
        paciente_email=paciente.email,
        data_vinculo=vinculo.data_vinculo,
        ativo=vinculo.ativo,
    )


async def criar_vinculo(
    db: AsyncSession,
    profissional_id: uuid.UUID,
    paciente_email: str,
) -> VinculoDetail:
    paciente = await queries.buscar_paciente_por_email(db, paciente_email)

    if paciente is None:
        raise PacienteNaoEncontradoError

    if paciente.role != "paciente" or not paciente.is_active:
        raise PacienteInvalidoError("paciente inválido ou inativo")

    try:
        vinculo = await queries.criar_vinculo(db, paciente.id, profissional_id)
        await db.commit()

    except IntegrityError as exc:
        await db.rollback()

        existente = await queries.buscar_vinculo_ativo(db, paciente.id, profissional_id)

        if existente is not None:
            raise VinculoJaExisteError from exc

        raise

    return _para_detalhe(vinculo, paciente)


async def desvincular(
    db: AsyncSession,
    profissional_id: uuid.UUID,
    paciente_id: uuid.UUID,
) -> None:
    vinculo = await queries.buscar_vinculo_ativo(db, paciente_id, profissional_id)

    if vinculo is None:
        raise VinculoNaoEncontradoError

    queries.encerrar_vinculo(vinculo)
    await db.commit()


async def listar_vinculos(
    db: AsyncSession,
    profissional_id: uuid.UUID,
) -> VinculoListResponse:
    pares = await queries.listar_vinculos_ativos(db, profissional_id)

    return VinculoListResponse(
        itens=[_para_detalhe(vinculo, paciente) for vinculo, paciente in pares]
    )
