"""Leitura e atualização do perfil do próprio usuário (/users/me — US-023).

O perfil agrega os dados de `users` com o bloco opcional de `profissionais`
(só para role = profissional). A atualização é parcial: só os campos
enviados no payload são alterados; o que pode ser enviado é travado pelo
schema `UserUpdate` (role, id, status e senha nem chegam aqui).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.policies import tem_papel
from app.models.profissional import Profissional
from app.models.user import User
from app.schemas.profissionais import ProfissionalPerfilRead
from app.schemas.user import UserRead, UserUpdate
from app.schemas.usuario import TipoUsuario


class DadosProfissionaisNaoPermitidosError(Exception):
    pass


def _para_leitura(user: User, profissional: Profissional | None) -> UserRead:
    perfil = UserRead.model_validate(user)

    if tem_papel(user, TipoUsuario.PROFISSIONAL):
        perfil.profissional = (
            ProfissionalPerfilRead.model_validate(profissional)
            if profissional is not None
            else ProfissionalPerfilRead()
        )

    return perfil


async def _buscar_profissional(db: AsyncSession, user: User) -> Profissional | None:
    if not tem_papel(user, TipoUsuario.PROFISSIONAL):
        return None
    return await db.get(Profissional, user.id)


async def obter_perfil(db: AsyncSession, user: User) -> UserRead:
    return _para_leitura(user, await _buscar_profissional(db, user))


async def atualizar_perfil(db: AsyncSession, user: User, dados: UserUpdate) -> UserRead:
    alteracoes = dados.model_dump(exclude_unset=True, exclude={"profissional"})
    alteracoes_profissional = (
        dados.profissional.model_dump(exclude_unset=True) if dados.profissional else {}
    )

    if alteracoes_profissional and not tem_papel(user, TipoUsuario.PROFISSIONAL):
        raise DadosProfissionaisNaoPermitidosError

    for campo, valor in alteracoes.items():
        setattr(user, campo, valor)

    profissional = await _buscar_profissional(db, user)

    if alteracoes_profissional:
        if profissional is None:
            profissional = Profissional(usuario_id=user.id, vinculado_hality=False)
            db.add(profissional)

        for campo, valor in alteracoes_profissional.items():
            setattr(profissional, campo, valor)

    await db.commit()

    return _para_leitura(user, profissional)
