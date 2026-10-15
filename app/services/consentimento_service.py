"""Consentimento por finalidade: registro auditável e revogável (US-020).

Regras centrais, chamadas por registro, convite, Google e perfil:

* cada decisão é um evento novo em `consentimento_eventos` (append-only) —
  revogar é gravar `aceito = false`, nunca alterar o evento anterior;
* o estado vigente de uma finalidade é o evento mais recente dela, e só vale
  se estiver na versão vigente do termo (`app/core/consentimentos.py`);
* só o tratamento de dados de saúde é obrigatório para cadastrar/ativar; recusar
  o uso da imagem para treino não impede nada;
* quem coleta a decisão nunca decide pelo titular: o ator é sempre o usuário
  autenticado (ou o próprio titular, no registro) — nenhum fluxo grava
  consentimento "em nome" de outra pessoa;
* cada evento também é auditado (sem texto clínico) na mesma transação.

As funções `gravar_*` não fazem commit: o chamador controla a transação.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.policies import papel_canonico
from app.core.consentimentos import (
    TERMOS,
    Finalidade,
    OrigemConsentimento,
    TermoConsentimento,
)
from app.db import auditoria_queries, consentimento_queries
from app.models.consentimento import ConsentimentoEvento
from app.models.user import User
from app.schemas.consentimento import (
    ConsentimentoEstado,
    ConsentimentosResponse,
    DecisaoConsentimento,
    TermoRead,
    TermosResponse,
)


class VersaoDesatualizadaError(Exception):
    """A decisão foi dada para uma versão do termo que não é a vigente."""

    def __init__(self, finalidade: Finalidade, versao_vigente: str) -> None:
        self.finalidade = finalidade
        self.versao_vigente = versao_vigente
        super().__init__(f"{finalidade}: versão vigente é {versao_vigente}")


class DecisaoDuplicadaError(Exception):
    """A mesma finalidade veio mais de uma vez no mesmo envio."""


class TratamentoObrigatorioError(Exception):
    """Cadastro/ativação sem aceite do tratamento de dados de saúde."""


def listar_termos() -> TermosResponse:
    return TermosResponse(
        itens=[
            TermoRead(
                finalidade=termo.finalidade,
                versao=termo.versao,
                obrigatorio=termo.obrigatorio,
                titulo=termo.titulo,
                texto=termo.texto,
            )
            for termo in TERMOS.values()
        ]
    )


def _validar_versao(decisao: DecisaoConsentimento) -> TermoConsentimento:
    termo = TERMOS[decisao.finalidade]
    if decisao.versao != termo.versao:
        raise VersaoDesatualizadaError(decisao.finalidade, termo.versao)
    return termo


def validar_decisoes_cadastro(decisoes: Sequence[DecisaoConsentimento]) -> None:
    """Valida o pacote de decisões de um cadastro ANTES de criar qualquer registro.

    Exige o aceite do tratamento na versão vigente; a finalidade de treino é
    opcional e, se ausente, fica "sem decisão" — nunca presumida como aceite.
    """
    finalidades = [decisao.finalidade for decisao in decisoes]
    if len(set(finalidades)) != len(finalidades):
        raise DecisaoDuplicadaError

    for decisao in decisoes:
        _validar_versao(decisao)

    tratamento = next((d for d in decisoes if d.finalidade == Finalidade.HEALTH_DATA), None)
    if tratamento is None or not tratamento.aceito:
        raise TratamentoObrigatorioError


async def gravar_decisoes(
    db: AsyncSession,
    *,
    titular: User,
    decisoes: Sequence[DecisaoConsentimento],
    origem: OrigemConsentimento,
    ator: User,
    referencia_coleta: str | None,
    operation_key: str | None = None,
) -> list[ConsentimentoEvento]:
    """Grava um evento (e sua auditoria) por decisão, sem commit.

    ``ator`` é quem coletou a decisão; para o titular decidindo por si é ele
    mesmo. O texto do termo nunca vai para o evento — só finalidade e versão.
    """
    eventos: list[ConsentimentoEvento] = []
    for decisao in decisoes:
        _validar_versao(decisao)
        evento = await consentimento_queries.inserir_evento(
            db,
            titular_id=titular.id,
            finalidade=decisao.finalidade.value,
            versao=decisao.versao,
            aceito=decisao.aceito,
            origem=origem.value,
            ator_id=ator.id,
            ator_papel=papel_canonico(ator),
            referencia_coleta=referencia_coleta,
        )
        await auditoria_queries.registrar_mutacao(
            db,
            ator,
            "consentimento.registrar",
            "consentimento",
            evento.id,
            metadata={
                "finalidade": evento.finalidade,
                "versao": evento.versao,
                "aceito": evento.aceito,
                "origem": evento.origem,
                "titular": str(titular.id),
            },
            operation_key=operation_key if len(decisoes) == 1 else None,
        )
        eventos.append(evento)
    return eventos


def _montar_estado(
    termo: TermoConsentimento, evento: ConsentimentoEvento | None
) -> ConsentimentoEstado:
    na_versao_vigente = evento is not None and evento.versao == termo.versao
    return ConsentimentoEstado(
        finalidade=termo.finalidade,
        obrigatorio=termo.obrigatorio,
        versao_vigente=termo.versao,
        versao_decidida=evento.versao if evento else None,
        aceito=evento.aceito if evento else None,
        vigente=bool(evento and evento.aceito and na_versao_vigente),
        requer_decisao=not na_versao_vigente,
        decidido_em=evento.registrado_em if evento else None,
    )


async def obter_estado(db: AsyncSession, titular_id: uuid.UUID) -> ConsentimentosResponse:
    ultimos = await consentimento_queries.ultimos_eventos(db, titular_id)
    estados = [
        _montar_estado(termo, ultimos.get(termo.finalidade.value)) for termo in TERMOS.values()
    ]
    # Compara por id (monotônico), não por data: mais simples e imune a fuso.
    mais_recente = max(ultimos.values(), key=lambda evento: evento.id, default=None)
    return ConsentimentosResponse(
        consentimentos=estados, recorded_at=mais_recente.registrado_em if mais_recente else None
    )


async def finalidade_vigente(
    db: AsyncSession, titular_id: uuid.UUID, finalidade: Finalidade
) -> bool:
    """True se o titular aceitou a finalidade na versão vigente do termo.

    É a consulta que diagnóstico e uma futura exportação devem usar: por
    exemplo, só considerar uma imagem para treino se `image_training` estiver
    vigente. Sem decisão, recusa, revogação ou versão antiga -> False.
    """
    ultimos = await consentimento_queries.ultimos_eventos(db, titular_id)
    evento = ultimos.get(finalidade.value)
    return bool(evento and evento.aceito and evento.versao == TERMOS[finalidade].versao)


async def registrar_decisao_do_titular(
    db: AsyncSession,
    *,
    titular: User,
    decisao: DecisaoConsentimento,
    referencia_coleta: str | None,
    operation_key: str | None = None,
) -> ConsentimentosResponse:
    """O próprio titular decide (ou revoga) uma finalidade pelo perfil."""
    _validar_versao(decisao)
    await auditoria_queries.validar_chave_operacao(
        db,
        actor=titular,
        action="consentimento.registrar",
        resource="consentimento",
        resource_id="novo",
        operation_key=operation_key,
    )
    (evento,) = await gravar_decisoes(
        db,
        titular=titular,
        decisoes=[decisao],
        origem=OrigemConsentimento.PERFIL,
        ator=titular,
        referencia_coleta=referencia_coleta,
        operation_key=operation_key,
    )
    await db.commit()

    estado = await obter_estado(db, titular.id)
    return estado.model_copy(update={"recorded_at": evento.registrado_em})


async def consultar_estado_como_admin(
    db: AsyncSession, admin: User, titular_id: uuid.UUID
) -> ConsentimentosResponse | None:
    """Leitura administrativa (auditada). `None` se o titular não existe."""
    if await db.get(User, titular_id) is None:
        return None
    await auditoria_queries.registrar_acesso(
        db,
        actor=admin,
        action="consentimento.consultar",
        resource="usuario",
        resource_id=str(titular_id),
    )
    await db.commit()
    return await obter_estado(db, titular_id)
