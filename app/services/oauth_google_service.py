"""Login com Google para paciente (US-012 / TASK-107).

Fluxo, todo conduzido pelo backend:

1. ``iniciar_autorizacao``: gera state, nonce e PKCE, persiste o fluxo (só o hash
   do state) e devolve a URL do Google.
2. ``processar_callback``: confere o state (cookie do navegador + fluxo de uso
   único), troca o código no Google, valida o ID token e resolve a identidade.
   Nunca devolve token: no sucesso emite um *código de troca* de uso único e
   curtíssimo; na falha devolve um código de erro recuperável.
3. ``trocar_codigo``: o frontend entrega o código de troca; se for um cadastro
   novo, só aqui — com o consentimento de tratamento aceito — a conta é criada.

Regras de segurança:

* o vínculo é por (provider, ``sub``); e-mail nunca vincula sozinho. Um e-mail
  Google igual ao de uma conta existente NÃO é vinculado: devolve
  ``conta_existente`` (vincular exige uma ação autenticada do titular, fora
  deste corte);
* só paciente: conta de profissional/admin (por vínculo ou por e-mail) é barrada;
* nenhuma conta parcial: a conta nasce na troca, junto com o consentimento, na
  mesma transação;
* tentativas e falhas vão para a auditoria só com identificadores e o motivo —
  sem token, e-mail ou perfil.
"""

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google import (
    CodigoRejeitadoError,
    EmailNaoVerificadoError,
    GoogleOAuthProvider,
    IdTokenInvalidoError,
    ProvedorIndisponivelError,
    gerar_code_verifier,
)
from app.auth.policies import tem_papel
from app.auth.users import password_helper
from app.core.consentimentos import OrigemConsentimento
from app.db import auditoria_queries, oauth_queries, user_queries
from app.models.oauth_fluxo import ESTADO_AUTENTICADO, ESTADO_FALHOU, OAuthFluxo
from app.models.user import User
from app.schemas.consentimento import DecisaoConsentimento
from app.schemas.usuario import TipoUsuario
from app.services import consentimento_service

logger = logging.getLogger("app.auth.google")

PROVIDER = "google"
RECURSO_AUDITORIA = "oauth_google"
FLUXO_DESCONHECIDO = "desconhecido"

STATE_TTL = timedelta(minutes=10)
CODIGO_TROCA_TTL = timedelta(minutes=2)
RETENCAO_FLUXOS = timedelta(days=1)
TAMANHO_MAXIMO_STATE = 128
TAMANHO_MAXIMO_CODIGO = 2048


class ErroLogin(StrEnum):
    """Códigos devolvidos ao frontend em `?erro=`. Todos são recuperáveis."""

    CANCELADO = "cancelado"
    ESTADO_INVALIDO = "estado_invalido"
    CALLBACK_INVALIDO = "callback_invalido"
    ERRO_PROVEDOR = "erro_provedor"
    PROVEDOR_INDISPONIVEL = "provedor_indisponivel"
    IDENTIDADE_INVALIDA = "identidade_invalida"
    EMAIL_NAO_VERIFICADO = "email_nao_verificado"
    CONTA_EXISTENTE = "conta_existente"
    PAPEL_NAO_PERMITIDO = "papel_nao_permitido"
    CONTA_INATIVA = "conta_inativa"


class Etapa(StrEnum):
    """O que o frontend deve fazer depois do callback."""

    SESSAO = "sessao"  # conta já existe: trocar o código por sessão
    CONSENTIMENTO = "consentimento"  # conta nova: coletar consentimento antes de trocar


class CodigoTrocaInvalidoError(Exception):
    """Código de troca desconhecido, expirado, já usado ou de fluxo que falhou."""


class ContaExistenteError(Exception):
    """Já existe conta com esse e-mail/identidade; não vinculamos automaticamente."""


class PapelNaoPermitidoError(Exception):
    """O login Google só vale para paciente."""


class ContaInativaError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ResultadoCallback:
    erro: ErroLogin | None = None
    codigo: str | None = None
    etapa: Etapa | None = None


def _agora() -> datetime:
    return datetime.now(UTC)


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


async def _auditar(
    db: AsyncSession,
    acao: str,
    fluxo_id: uuid.UUID | str,
    resultado: str,
    *,
    usuario: User | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await auditoria_queries.registrar_acesso(
        db,
        actor=usuario,
        action=acao,
        resource=RECURSO_AUDITORIA,
        resource_id=str(fluxo_id),
        result=resultado,
        metadata={"provider": PROVIDER, **(metadata or {})},
    )


async def iniciar_autorizacao(db: AsyncSession, provider: GoogleOAuthProvider) -> tuple[str, str]:
    """Cria o fluxo e devolve ``(url_do_google, state)``; o state vira cookie no endpoint."""
    agora = _agora()
    await oauth_queries.purgar_fluxos_antigos(db, antes_de=agora - RETENCAO_FLUXOS)

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = gerar_code_verifier()
    fluxo = await oauth_queries.criar_fluxo(
        db,
        provider=PROVIDER,
        state_hash=_hash(state),
        nonce=nonce,
        code_verifier=code_verifier,
        expira_em=agora + STATE_TTL,
    )
    await _auditar(db, "auth.google.autorizar", fluxo.id, "sucesso")
    await db.commit()

    url = provider.authorization_url(state=state, nonce=nonce, code_verifier=code_verifier)
    return url, state


async def _falha_sem_fluxo(db: AsyncSession, erro: ErroLogin) -> ResultadoCallback:
    logger.warning("google_callback_recusado motivo=%s", erro.value)
    await _auditar(
        db, "auth.google.callback", FLUXO_DESCONHECIDO, "falha", metadata={"motivo": erro.value}
    )
    await db.commit()
    return ResultadoCallback(erro=erro)


async def _falhar(
    db: AsyncSession, fluxo: OAuthFluxo, erro: ErroLogin, *, usuario: User | None = None
) -> ResultadoCallback:
    logger.warning("google_callback_falhou fluxo=%s motivo=%s", fluxo.id, erro.value)
    fluxo.estado = ESTADO_FALHOU
    fluxo.motivo_falha = erro.value
    fluxo.email = None
    fluxo.nome = None
    await _auditar(
        db,
        "auth.google.callback",
        fluxo.id,
        "falha",
        usuario=usuario,
        metadata={"motivo": erro.value},
    )
    await db.commit()
    return ResultadoCallback(erro=erro)


def _erro_do_usuario(usuario: User) -> ErroLogin | None:
    if not tem_papel(usuario, TipoUsuario.PACIENTE):
        return ErroLogin.PAPEL_NAO_PERMITIDO
    if not usuario.is_active:
        return ErroLogin.CONTA_INATIVA
    return None


def _state_bem_formado(state: str | None) -> bool:
    return bool(state) and len(state) <= TAMANHO_MAXIMO_STATE and state.isascii()


async def processar_callback(
    db: AsyncSession,
    provider: GoogleOAuthProvider,
    *,
    state: str | None,
    state_cookie: str | None,
    code: str | None,
    error: str | None,
) -> ResultadoCallback:
    # O cookie amarra o fluxo ao navegador que o iniciou (evita "login CSRF"): o
    # state da URL sozinho não basta.
    if (
        not _state_bem_formado(state)
        or not state_cookie
        or not state_cookie.isascii()
        or not secrets.compare_digest(state.encode(), state_cookie.encode())
    ):
        return await _falha_sem_fluxo(db, ErroLogin.ESTADO_INVALIDO)

    fluxo = await oauth_queries.reivindicar_callback(db, state_hash=_hash(state), agora=_agora())
    if fluxo is None:  # desconhecido, expirado ou callback repetido
        return await _falha_sem_fluxo(db, ErroLogin.ESTADO_INVALIDO)
    # Confirma a reivindicação antes de qualquer chamada de rede.
    await db.commit()

    if error:
        motivo = ErroLogin.CANCELADO if error == "access_denied" else ErroLogin.ERRO_PROVEDOR
        return await _falhar(db, fluxo, motivo)
    if not code or len(code) > TAMANHO_MAXIMO_CODIGO:
        return await _falhar(db, fluxo, ErroLogin.CALLBACK_INVALIDO)

    try:
        google = await provider.obter_identidade(
            code=code, code_verifier=fluxo.code_verifier, nonce=fluxo.nonce
        )
    except ProvedorIndisponivelError:
        return await _falhar(db, fluxo, ErroLogin.PROVEDOR_INDISPONIVEL)
    except CodigoRejeitadoError:
        return await _falhar(db, fluxo, ErroLogin.CALLBACK_INVALIDO)
    except EmailNaoVerificadoError:
        return await _falhar(db, fluxo, ErroLogin.EMAIL_NAO_VERIFICADO)
    except IdTokenInvalidoError:
        return await _falhar(db, fluxo, ErroLogin.IDENTIDADE_INVALIDA)

    identidade = await oauth_queries.buscar_identidade(
        db, provider=PROVIDER, subject=google.subject
    )
    if identidade is not None:
        usuario = await db.get(User, identidade.user_id)
        erro = _erro_do_usuario(usuario) if usuario else ErroLogin.CONTA_INATIVA
        if erro is not None:
            return await _falhar(db, fluxo, erro, usuario=usuario)
        fluxo.user_id = usuario.id
        etapa = Etapa.SESSAO
    else:
        existente = await user_queries.buscar_por_email(db, google.email)
        if existente is not None:
            # Sem vínculo silencioso por e-mail (AC-014).
            erro = (
                ErroLogin.CONTA_EXISTENTE
                if tem_papel(existente, TipoUsuario.PACIENTE)
                else ErroLogin.PAPEL_NAO_PERMITIDO
            )
            return await _falhar(db, fluxo, erro)
        fluxo.email = google.email
        fluxo.nome = google.nome
        etapa = Etapa.CONSENTIMENTO

    codigo = secrets.token_urlsafe(32)
    fluxo.estado = ESTADO_AUTENTICADO
    fluxo.subject = google.subject
    fluxo.codigo_hash = _hash(codigo)
    fluxo.codigo_expira_em = _agora() + CODIGO_TROCA_TTL
    await _auditar(db, "auth.google.callback", fluxo.id, "sucesso", metadata={"etapa": etapa.value})
    await db.commit()
    return ResultadoCallback(codigo=codigo, etapa=etapa)


async def trocar_codigo(
    db: AsyncSession,
    *,
    codigo: str,
    consentimentos: list[DecisaoConsentimento],
    referencia_coleta: str | None,
) -> User:
    """Gasta o código de troca e devolve o usuário autenticado (a sessão é do endpoint)."""
    agora = _agora()
    fluxo = None
    if codigo and len(codigo) <= TAMANHO_MAXIMO_CODIGO:
        fluxo = await oauth_queries.buscar_fluxo_para_troca(
            db, codigo_hash=_hash(codigo), agora=agora
        )
    if fluxo is None:
        await _auditar(
            db,
            "auth.google.trocar",
            FLUXO_DESCONHECIDO,
            "falha",
            metadata={"motivo": "codigo_invalido"},
        )
        await db.commit()
        raise CodigoTrocaInvalidoError

    if fluxo.user_id is not None:
        return await _trocar_para_conta_existente(db, fluxo)
    return await _trocar_criando_conta(
        db, fluxo, consentimentos=consentimentos, referencia_coleta=referencia_coleta
    )


async def _recusar_troca(
    db: AsyncSession, fluxo: OAuthFluxo, erro: ErroLogin, usuario: User | None
) -> None:
    fluxo.estado = ESTADO_FALHOU
    fluxo.motivo_falha = erro.value
    await _auditar(
        db,
        "auth.google.trocar",
        fluxo.id,
        "falha",
        usuario=usuario,
        metadata={"motivo": erro.value},
    )
    await db.commit()


async def _trocar_para_conta_existente(db: AsyncSession, fluxo: OAuthFluxo) -> User:
    usuario = await db.get(User, fluxo.user_id)
    erro = _erro_do_usuario(usuario) if usuario else ErroLogin.CONTA_INATIVA
    if erro is not None:
        # O papel/estado pode ter mudado entre o callback e a troca.
        await _recusar_troca(db, fluxo, erro, usuario)
        if erro is ErroLogin.PAPEL_NAO_PERMITIDO:
            raise PapelNaoPermitidoError
        raise ContaInativaError

    if not await oauth_queries.consumir_codigo_de_troca(db, fluxo_id=fluxo.id):
        await db.rollback()
        raise CodigoTrocaInvalidoError

    identidade = await oauth_queries.buscar_identidade(
        db, provider=PROVIDER, subject=fluxo.subject or ""
    )
    if identidade is not None:
        identidade.ultimo_login_em = _agora()
    usuario.is_verified = True
    fluxo.email = None
    fluxo.nome = None
    await _auditar(db, "auth.google.trocar", fluxo.id, "sucesso", usuario=usuario)
    await db.commit()
    return usuario


async def _trocar_criando_conta(
    db: AsyncSession,
    fluxo: OAuthFluxo,
    *,
    consentimentos: list[DecisaoConsentimento],
    referencia_coleta: str | None,
) -> User:
    # Valida o consentimento ANTES de gastar o código: se faltar o aceite do
    # tratamento, nada é criado e o mesmo código ainda vale até expirar.
    consentimento_service.validar_decisoes_cadastro(consentimentos)

    email, nome, subject = fluxo.email, fluxo.nome, fluxo.subject
    if not email or not nome or not subject:
        raise CodigoTrocaInvalidoError
    if await user_queries.email_em_uso(db, email):
        await _recusar_troca(db, fluxo, ErroLogin.CONTA_EXISTENTE, None)
        raise ContaExistenteError

    fluxo_id = fluxo.id
    try:
        if not await oauth_queries.consumir_codigo_de_troca(db, fluxo_id=fluxo_id):
            await db.rollback()
            raise CodigoTrocaInvalidoError

        usuario = await user_queries.criar_usuario(
            db,
            name=nome,
            email=email,
            phone=None,
            role=TipoUsuario.PACIENTE.value,
            # Conta sem senha utilizável: o acesso é pelo Google.
            hashed_password=password_helper.hash(secrets.token_urlsafe(32)),
            is_verified=True,
        )
        await oauth_queries.criar_identidade(
            db, user_id=usuario.id, provider=PROVIDER, subject=subject
        )
        await consentimento_service.gravar_decisoes(
            db,
            titular=usuario,
            decisoes=consentimentos,
            origem=OrigemConsentimento.GOOGLE,
            ator=usuario,
            referencia_coleta=referencia_coleta,
        )
        fluxo = await db.get(OAuthFluxo, fluxo_id, populate_existing=True)
        fluxo.user_id = usuario.id
        fluxo.email = None
        fluxo.nome = None
        await _auditar(db, "auth.google.trocar", fluxo_id, "sucesso", usuario=usuario)
        await db.commit()
    except IntegrityError as exc:
        # E-mail ou identidade criados por outra requisição no meio do caminho.
        await db.rollback()
        await _auditar(
            db,
            "auth.google.trocar",
            fluxo_id,
            "falha",
            metadata={"motivo": ErroLogin.CONTA_EXISTENTE.value},
        )
        await db.commit()
        raise ContaExistenteError from exc

    return usuario
