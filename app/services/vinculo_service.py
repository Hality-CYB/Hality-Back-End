"""Criação, listagem e desvinculação do vínculo paciente-profissional (DEC-01).

DEC-01: o paciente se cadastra sozinho na plataforma (sem intervenção do
profissional). O profissional seleciona/"puxa" um paciente já cadastrado
pelo e-mail — não há convite, credencial de profissional ou consentimento
por vínculo (fora de escopo desta decisão).

O profissional também pode cadastrar um paciente novo, que já nasce vinculado
a ele (``POST /pacientes``, ver ``paciente_service.criar_paciente``).
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import auditoria_queries, user_queries
from app.db import paciente_profissional_queries as queries
from app.models.paciente_profissional import PacienteProfissional
from app.models.user import User
from app.schemas.paciente_profissional import (
    AdminVinculoDetail,
    AdminVinculoListResponse,
    VinculoDetail,
    VinculoListResponse,
)
from app.schemas.usuario import TipoUsuario


class PacienteNaoEncontradoError(Exception):
    pass


class PacienteInvalidoError(Exception):
    def __init__(self, motivo: str) -> None:
        self.motivo = motivo
        super().__init__(motivo)


class ProfissionalInvalidoError(Exception):
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

    _validar_paciente(paciente)
    vinculo = await _persistir_vinculo(db, paciente.id, profissional_id)
    return _para_detalhe(vinculo, paciente)


def _validar_paciente(paciente: User) -> None:
    if paciente.role != TipoUsuario.PACIENTE or not paciente.is_active:
        raise PacienteInvalidoError("paciente inválido ou inativo")


async def _persistir_vinculo(
    db: AsyncSession,
    paciente_id: uuid.UUID,
    profissional_id: uuid.UUID,
) -> PacienteProfissional:
    # Recebe ids, não objetos: o rollback expira tudo na sessão, e ler um
    # atributo depois dele dispararia um refresh implícito (IO fora do
    # greenlet do driver assíncrono).
    try:
        vinculo = await queries.criar_vinculo(db, paciente_id, profissional_id)
        await db.commit()

    except IntegrityError as exc:
        await db.rollback()

        existente = await queries.buscar_vinculo_ativo(db, paciente_id, profissional_id)

        if existente is not None:
            raise VinculoJaExisteError from exc

        raise

    return vinculo


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


def _para_detalhe_admin(
    vinculo: PacienteProfissional, paciente_nome: str, profissional_nome: str
) -> AdminVinculoDetail:
    return AdminVinculoDetail(
        id=vinculo.id,
        paciente_id=vinculo.paciente_id,
        paciente_nome=paciente_nome,
        profissional_id=vinculo.profissional_id,
        profissional_nome=profissional_nome,
        data_vinculo=vinculo.data_vinculo,
        ativo=vinculo.ativo,
        encerrado_em=vinculo.encerrado_em,
    )


async def _validar_par(
    db: AsyncSession,
    paciente_id: uuid.UUID,
    profissional_id: uuid.UUID,
) -> tuple[User, User]:
    paciente = await user_queries.buscar_usuario(db, paciente_id)
    if paciente is None:
        raise PacienteInvalidoError("paciente não encontrado")
    _validar_paciente(paciente)

    encontrado = await user_queries.buscar_usuario_com_profissional(db, profissional_id)
    if encontrado is None:
        raise ProfissionalInvalidoError("profissional não encontrado")
    profissional, dados_profissional = encontrado
    if (
        profissional.role != TipoUsuario.PROFISSIONAL
        or not profissional.is_active
        or dados_profissional is None
    ):
        raise ProfissionalInvalidoError("profissional inválido ou inativo")

    return paciente, profissional


async def listar_vinculos_admin(
    db: AsyncSession,
    *,
    pagina: int,
    limite: int,
    paciente_id: uuid.UUID | None,
    profissional_id: uuid.UUID | None,
    ativo: bool | None,
) -> AdminVinculoListResponse:
    linhas, total = await queries.listar_vinculos(
        db,
        paciente_id=paciente_id,
        profissional_id=profissional_id,
        ativo=ativo,
        offset=(pagina - 1) * limite,
        limite=limite,
    )
    return AdminVinculoListResponse(
        itens=[_para_detalhe_admin(*linha) for linha in linhas],
        pagina=pagina,
        limite=limite,
        total=total,
        total_paginas=(total + limite - 1) // limite,
    )


async def criar_vinculo_admin(
    db: AsyncSession,
    paciente_id: uuid.UUID,
    profissional_id: uuid.UUID,
    actor: User,
    operation_key: str | None = None,
) -> AdminVinculoDetail:
    paciente, profissional = await _validar_par(db, paciente_id, profissional_id)
    paciente_nome, profissional_nome = paciente.name, profissional.name
    await auditoria_queries.validar_chave_operacao(
        db,
        actor=actor,
        action="vinculo.criar",
        resource="vinculo",
        resource_id="novo",
        operation_key=operation_key,
    )

    try:
        vinculo = await queries.criar_vinculo(db, paciente_id, profissional_id)
    except IntegrityError as exc:
        await db.rollback()
        if await queries.buscar_vinculo_ativo(db, paciente_id, profissional_id) is not None:
            raise VinculoJaExisteError from exc
        raise
    await auditoria_queries.registrar_mutacao(
        db,
        actor,
        "vinculo.criar",
        "vinculo",
        vinculo.id,
        metadata={"paciente_id": str(paciente_id), "profissional_id": str(profissional_id)},
        operation_key=operation_key,
    )
    await db.commit()
    return _para_detalhe_admin(vinculo, paciente_nome, profissional_nome)


async def _reativar(db: AsyncSession, vinculo: PacienteProfissional) -> None:
    await _validar_par(db, vinculo.paciente_id, vinculo.profissional_id)
    queries.reativar_vinculo(vinculo)

    try:
        await db.commit()

    except IntegrityError as exc:
        await db.rollback()
        raise VinculoJaExisteError from exc


async def atualizar_vinculo_admin(
    db: AsyncSession,
    vinculo_id: int,
    ativo: bool,
    actor: User,
    operation_key: str | None = None,
) -> AdminVinculoDetail:
    encontrado = await queries.buscar_vinculo_detalhado(db, vinculo_id)
    if encontrado is None:
        raise VinculoNaoEncontradoError
    vinculo, paciente_nome, profissional_nome = encontrado
    acao = "vinculo.reativar" if ativo and not vinculo.ativo else "vinculo.desativar"
    await auditoria_queries.validar_chave_operacao(
        db,
        actor=actor,
        action=acao,
        resource="vinculo",
        resource_id=vinculo.id,
        operation_key=operation_key,
    )

    if ativo and not vinculo.ativo:
        await _validar_par(db, vinculo.paciente_id, vinculo.profissional_id)
        queries.reativar_vinculo(vinculo)
    elif not ativo and vinculo.ativo:
        queries.encerrar_vinculo(vinculo)
    else:
        return _para_detalhe_admin(vinculo, paciente_nome, profissional_nome)

    try:
        await auditoria_queries.registrar_mutacao(
            db,
            actor,
            acao,
            "vinculo",
            vinculo.id,
            operation_key=operation_key,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise VinculoJaExisteError from exc

    return _para_detalhe_admin(vinculo, paciente_nome, profissional_nome)


async def encerrar_vinculo_admin(
    db: AsyncSession,
    vinculo_id: int,
    actor: User,
    operation_key: str | None = None,
) -> None:
    vinculo = await queries.buscar_vinculo(db, vinculo_id)
    if vinculo is None or not vinculo.ativo:
        raise VinculoNaoEncontradoError

    await auditoria_queries.validar_chave_operacao(
        db,
        actor=actor,
        action="vinculo.remover",
        resource="vinculo",
        resource_id=vinculo.id,
        operation_key=operation_key,
    )
    queries.encerrar_vinculo(vinculo)
    await auditoria_queries.registrar_mutacao(
        db,
        actor,
        "vinculo.remover",
        "vinculo",
        vinculo.id,
        metadata={"motivo": "correcao_administrativa"},
        operation_key=operation_key,
    )
    await db.commit()
