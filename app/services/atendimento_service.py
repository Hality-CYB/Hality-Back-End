"""Contexto de atendimento: quem executa a ação (ator) e em nome de quem (titular).

Na autoavaliação, ator e titular são o mesmo usuário. No atendimento por
profissional (US-090), o titular é um paciente selecionado e só é aceito se
houver vínculo em `pacientes_profissionais` — o id do titular nunca é
confiado sem essa checagem, e o id do profissional vem sempre do token.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import vinculo_queries

# `seed.py` grava "profissional"; o docstring de User ainda cita "professional".
ROLES_PROFISSIONAL = frozenset({"profissional", "professional"})


class AtorNaoProfissionalError(Exception):
    pass


class VinculoInexistenteError(Exception):
    pass


class TitularIndisponivelError(Exception):
    pass


@dataclass(frozen=True)
class AtorAutenticado:
    id: uuid.UUID
    role: str

    @property
    def eh_profissional(self) -> bool:
        return self.role in ROLES_PROFISSIONAL


async def resolver_titular(
    db: AsyncSession,
    ator: AtorAutenticado,
    paciente_id: uuid.UUID | None,
) -> uuid.UUID:
    """Devolve o titular autorizado para `ator` agir.

    Sem `paciente_id` (ou com o próprio id), é autoavaliação. Com outro id,
    exige papel de profissional e vínculo com o paciente — levanta erro
    antes de qualquer leitura/escrita de anamnese ou imagem.
    """
    if paciente_id is None or paciente_id == ator.id:
        return ator.id

    if not ator.eh_profissional:
        raise AtorNaoProfissionalError

    if not await vinculo_queries.existe_vinculo(db, ator.id, paciente_id):
        raise VinculoInexistenteError

    if not await vinculo_queries.usuario_ativo(db, paciente_id):
        raise TitularIndisponivelError

    return paciente_id


async def pode_acessar_titular(
    db: AsyncSession,
    ator: AtorAutenticado,
    paciente_id: uuid.UUID,
) -> bool:
    if paciente_id == ator.id:
        return True

    return ator.eh_profissional and await vinculo_queries.existe_vinculo(db, ator.id, paciente_id)
