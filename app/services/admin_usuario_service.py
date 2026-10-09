"""CRUD administrativo de usuários e profissionais (US-110).

Invariante: `role == "profissional"` se e somente se existe a linha
correspondente em `profissionais`. Toda operação que mexe nas duas tabelas
faz um único commit.

Não usa `UserManager.create/update`: o adaptador SQLAlchemy do fastapi-users
faz commit internamente, o que quebraria a atomicidade de User + Profissional.
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.users import password_helper
from app.db import auditoria_queries, user_queries
from app.db import paciente_profissional_queries as vinculo_queries
from app.models.profissional import Profissional
from app.models.user import User
from app.schemas.admin_usuario import (
    AdminProfissionalDetail,
    AdminProfissionalUpdate,
    AdminUsuarioCreate,
    AdminUsuarioDetail,
    AdminUsuarioListResponse,
    AdminUsuarioUpdate,
    ProfissionalDados,
)
from app.schemas.usuario import TipoUsuario

_COLUNAS_USUARIO = {"nome": "name", "telefone": "phone", "ativo": "is_active", "role": "role"}


class UsuarioNaoEncontradoError(Exception):
    pass


class ProfissionalNaoEncontradoError(Exception):
    pass


class EmailJaCadastradoError(Exception):
    pass


class UltimoAdministradorError(Exception):
    pass


class TrocaDeRoleBloqueadaError(Exception):
    def __init__(self, motivo: str) -> None:
        self.motivo = motivo
        super().__init__(motivo)


def _para_detalhe(usuario: User, profissional: Profissional | None) -> AdminUsuarioDetail:
    return AdminUsuarioDetail(
        id=usuario.id,
        nome=usuario.name,
        email=usuario.email,
        telefone=usuario.phone,
        role=usuario.role,
        ativo=usuario.is_active,
        created_at=usuario.created_at,
        profissional=None
        if profissional is None
        else AdminProfissionalDetail(
            registro_profissional=profissional.registro_profissional,
            especialidade=profissional.especialidade,
            vinculado_hality=profissional.vinculado_hality,
        ),
    )


async def listar_usuarios(
    db: AsyncSession,
    *,
    pagina: int,
    limite: int,
    role: TipoUsuario | None,
    ativo: bool | None,
    busca: str | None,
) -> AdminUsuarioListResponse:
    linhas, total = await user_queries.listar_usuarios(
        db,
        role=role,
        ativo=ativo,
        busca=busca.strip() if busca else None,
        offset=(pagina - 1) * limite,
        limite=limite,
    )
    return AdminUsuarioListResponse(
        itens=[_para_detalhe(usuario, profissional) for usuario, profissional in linhas],
        pagina=pagina,
        limite=limite,
        total=total,
        total_paginas=(total + limite - 1) // limite,
    )


async def obter_usuario(db: AsyncSession, usuario_id: uuid.UUID) -> AdminUsuarioDetail:
    encontrado = await user_queries.buscar_usuario_com_profissional(db, usuario_id)
    if encontrado is None:
        raise UsuarioNaoEncontradoError
    return _para_detalhe(*encontrado)


async def criar_usuario(
    db: AsyncSession,
    dados: AdminUsuarioCreate,
    actor: User,
    operation_key: str | None = None,
) -> AdminUsuarioDetail:
    if await user_queries.email_em_uso(db, dados.email):
        raise EmailJaCadastradoError
    await auditoria_queries.validar_chave_operacao(
        db,
        actor=actor,
        action="usuario.criar",
        resource="usuario",
        resource_id="novo",
        operation_key=operation_key,
    )

    try:
        usuario = await user_queries.criar_usuario(
            db,
            name=dados.nome,
            email=dados.email,
            phone=dados.telefone,
            role=dados.role,
            hashed_password=password_helper.hash(dados.senha),
        )
        profissional = None
        if dados.role == TipoUsuario.PROFISSIONAL:
            dados_profissional = dados.profissional or ProfissionalDados()
            profissional = await user_queries.criar_profissional(
                db, usuario.id, **dados_profissional.model_dump()
            )
        await auditoria_queries.registrar_mutacao(
            db,
            actor,
            "usuario.criar",
            "usuario",
            usuario.id,
            metadata={"role": str(dados.role)},
            operation_key=operation_key,
        )
        await db.commit()

    except IntegrityError as exc:
        await db.rollback()
        if await user_queries.email_em_uso(db, dados.email):
            raise EmailJaCadastradoError from exc
        raise

    return _para_detalhe(usuario, profissional)


def _tem_acesso_admin(role: str, ativo: bool) -> bool:
    # Só `role = admin` dá acesso administrativo; `is_superuser` não conta
    # (ver app/auth/policies.py).
    return ativo and role == TipoUsuario.ADMIN


async def _garantir_outro_admin_se_perder_acesso(
    db: AsyncSession, usuario: User, campos: dict
) -> None:
    tinha_acesso = _tem_acesso_admin(usuario.role, usuario.is_active)
    tera_acesso = _tem_acesso_admin(
        campos.get("role", usuario.role),
        campos.get("ativo", usuario.is_active),
    )
    if not tinha_acesso or tera_acesso:
        return

    if not await user_queries.bloquear_outros_admins_efetivos(db, usuario.id):
        raise UltimoAdministradorError


async def _aplicar_troca_de_role(
    db: AsyncSession,
    usuario: User,
    profissional: Profissional | None,
    nova_role: TipoUsuario,
) -> Profissional | None:
    if usuario.role == TipoUsuario.PACIENTE and await vinculo_queries.paciente_tem_vinculo_ativo(
        db, usuario.id
    ):
        raise TrocaDeRoleBloqueadaError("paciente possui vínculos ativos")

    if nova_role == TipoUsuario.PROFISSIONAL:
        if profissional is not None:
            return profissional
        return await user_queries.criar_profissional(db, usuario.id)

    if profissional is None:
        return None

    tem_vinculos, tem_vinculos_ativos = await vinculo_queries.situacao_vinculos_do_profissional(
        db, usuario.id
    )
    if tem_vinculos_ativos:
        raise TrocaDeRoleBloqueadaError("profissional possui vínculos ativos")
    if tem_vinculos:
        # Apagar a linha de `profissionais` levaria o histórico de vínculos
        # junto (ON DELETE CASCADE).
        raise TrocaDeRoleBloqueadaError("profissional possui histórico de vínculos")

    await user_queries.remover_profissional(db, profissional)
    return None


async def atualizar_usuario(
    db: AsyncSession,
    usuario_id: uuid.UUID,
    dados: AdminUsuarioUpdate,
    actor: User,
    operation_key: str | None = None,
) -> AdminUsuarioDetail:
    encontrado = await user_queries.buscar_usuario_com_profissional(db, usuario_id)
    if encontrado is None:
        raise UsuarioNaoEncontradoError
    usuario, profissional = encontrado

    campos = dados.model_dump(exclude_unset=True)
    await auditoria_queries.validar_chave_operacao(
        db,
        actor=actor,
        action="usuario.desativar" if campos.get("ativo") is False else "usuario.editar",
        resource="usuario",
        resource_id=usuario.id,
        operation_key=operation_key,
    )
    await _garantir_outro_admin_se_perder_acesso(db, usuario, campos)

    nova_role = campos.get("role")
    if nova_role is not None and nova_role != usuario.role:
        profissional = await _aplicar_troca_de_role(db, usuario, profissional, nova_role)

    for campo, valor in campos.items():
        setattr(usuario, _COLUNAS_USUARIO[campo], valor)

    await auditoria_queries.registrar_mutacao(
        db,
        actor,
        "usuario.desativar" if campos.get("ativo") is False else "usuario.editar",
        "usuario",
        usuario.id,
        metadata={"campos": sorted(campos)},
        operation_key=operation_key,
    )
    await db.commit()
    return _para_detalhe(usuario, profissional)


async def atualizar_profissional(
    db: AsyncSession,
    usuario_id: uuid.UUID,
    dados: AdminProfissionalUpdate,
    actor: User,
    operation_key: str | None = None,
) -> AdminUsuarioDetail:
    encontrado = await user_queries.buscar_usuario_com_profissional(db, usuario_id)
    if encontrado is None or encontrado[1] is None:
        raise ProfissionalNaoEncontradoError
    usuario, profissional = encontrado
    await auditoria_queries.validar_chave_operacao(
        db,
        actor=actor,
        action="usuario.profissional.editar",
        resource="profissional",
        resource_id=usuario.id,
        operation_key=operation_key,
    )

    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(profissional, campo, valor)

    await auditoria_queries.registrar_mutacao(
        db,
        actor,
        "usuario.profissional.editar",
        "profissional",
        usuario.id,
        metadata={"campos": sorted(dados.model_dump(exclude_unset=True))},
        operation_key=operation_key,
    )
    await db.commit()
    return _para_detalhe(usuario, profissional)
