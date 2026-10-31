"""Cadastro público de paciente com consentimentos por finalidade (US-020).

Não usa `UserManager.create`: o adaptador do fastapi-users faz commit
internamente, o que deixaria um usuário sem consentimento registrado se a
gravação dos eventos falhasse. Aqui conta, eventos e auditoria saem no mesmo
commit.
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.users import password_helper
from app.core.consentimentos import OrigemConsentimento
from app.db import user_queries
from app.models.user import User
from app.schemas.user import RegistroCreate
from app.schemas.usuario import TipoUsuario
from app.services import consentimento_service


class EmailJaCadastradoError(Exception):
    pass


async def registrar_paciente(
    db: AsyncSession, dados: RegistroCreate, referencia_coleta: str | None
) -> User:
    # Valida as decisões antes de tocar no banco: sem aceite do tratamento
    # nenhuma conta (nem parcial) é criada.
    consentimento_service.validar_decisoes_cadastro(dados.consentimentos)

    if await user_queries.email_em_uso(db, dados.email):
        raise EmailJaCadastradoError

    try:
        usuario = await user_queries.criar_usuario(
            db,
            name=dados.name,
            email=dados.email,
            phone=dados.phone,
            data_nascimento=dados.data_nascimento,
            role=TipoUsuario.PACIENTE.value,
            hashed_password=password_helper.hash(dados.password),
        )
        await consentimento_service.gravar_decisoes(
            db,
            titular=usuario,
            decisoes=dados.consentimentos,
            origem=OrigemConsentimento.REGISTRO,
            ator=usuario,
            referencia_coleta=referencia_coleta,
        )
        await db.commit()

    except IntegrityError as exc:
        await db.rollback()
        if await user_queries.email_em_uso(db, dados.email):
            raise EmailJaCadastradoError from exc
        raise

    return usuario
