"""Solicitação pública e decisão administrativa atômica, com entrega pela outbox."""

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.users import password_helper
from app.db import auditoria_queries, user_queries
from app.models.identity_action import EmailOutbox
from app.models.solicitacao_profissional import SolicitacaoProfissional
from app.models.user import User
from app.schemas.solicitacao_profissional import (
    SolicitacaoProfissionalCreate,
    SolicitacoesProfissionaisRead,
)
from app.schemas.usuario import TipoUsuario
from app.services.identity_token_service import create_invitation


class ConflitoSolicitacaoError(Exception):
    pass


class SolicitacaoNaoEncontradaError(Exception):
    pass


async def solicitar(db: AsyncSession, dados: SolicitacaoProfissionalCreate) -> None:
    email = str(dados.email).lower()
    # Não altera contas existentes, nem dados de uma solicitação já enviada.
    if await user_queries.email_em_uso(db, email) or await db.scalar(
        select(SolicitacaoProfissional.id).where(SolicitacaoProfissional.email == email)
    ):
        raise ConflitoSolicitacaoError
    db.add(
        SolicitacaoProfissional(
            **dados.model_dump(exclude={"aceita_termos", "email"}),
            email=email,
            termos_aceitos_em=datetime.now(UTC),
        )
    )
    await db.commit()


async def listar(db: AsyncSession, status: str, pagina: int, limite: int):
    filtro = SolicitacaoProfissional.status == status
    total = await db.scalar(select(func.count()).select_from(SolicitacaoProfissional).where(filtro))
    itens = await db.scalars(
        select(SolicitacaoProfissional)
        .where(filtro)
        .order_by(SolicitacaoProfissional.created_at, SolicitacaoProfissional.id)
        .offset((pagina - 1) * limite)
        .limit(limite)
    )
    return SolicitacoesProfissionaisRead(
        itens=list(itens), total=total, pagina=pagina, total_paginas=(total + limite - 1) // limite
    )


async def decidir(db: AsyncSession, id: uuid.UUID, decisao: str, admin: User):
    solicitacao = await db.scalar(
        select(SolicitacaoProfissional).where(SolicitacaoProfissional.id == id).with_for_update()
    )
    if solicitacao is None:
        raise SolicitacaoNaoEncontradaError
    if solicitacao.status != "pendente":
        raise ConflitoSolicitacaoError
    if decisao == "aprovada":
        if await user_queries.email_em_uso(db, solicitacao.email):
            raise ConflitoSolicitacaoError
        usuario = await user_queries.criar_usuario(
            db,
            name=solicitacao.nome,
            email=solicitacao.email,
            phone=solicitacao.telefone,
            role=TipoUsuario.PROFISSIONAL,
            hashed_password=password_helper.hash(secrets.token_urlsafe(32)),
            is_active=False,
            is_verified=False,
        )
        await user_queries.criar_profissional(
            db,
            usuario.id,
            registro_profissional=solicitacao.registro_profissional,
            especialidade=solicitacao.especialidade,
            vinculado_hality=False,
        )
        correlation_id = await create_invitation(db, usuario, commit=False)
        email = await db.scalar(
            select(EmailOutbox).where(EmailOutbox.correlation_id == correlation_id)
        )
        email.purpose = "professional_approved"
        solicitacao.usuario_id = usuario.id
    else:
        db.add(
            EmailOutbox(
                solicitacao_id=solicitacao.id,
                recipient_email=solicitacao.email,
                purpose="professional_rejected",
                status="queued",
                correlation_id=uuid.uuid4().hex,
            )
        )
    solicitacao.status = decisao
    solicitacao.decidido_em = datetime.now(UTC)
    solicitacao.decidido_por = admin.id
    await auditoria_queries.registrar_mutacao(
        db, admin, f"profissional.solicitacao.{decisao}", "solicitacao_profissional", solicitacao.id
    )
    await db.commit()
    return solicitacao
