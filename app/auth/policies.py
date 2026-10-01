"""Políticas de autorização reutilizáveis: papel do usuário e acesso a dados de paciente.

Este módulo é a **única** fonte de regra de autorização da API. Endpoints não checam
``role`` nem comparam ``paciente_id`` por conta própria:

* papel -> ``exigir_papeis`` (``app/api/deps.py``), que usa ``normalizar_papel``;
* acesso ao paciente dono do recurso -> ``pode_acessar_paciente``, que usa a query
  de vínculo em ``app/db/paciente_profissional_queries.py``.

Convenções — valem para todos os recursos clínicos (anamnese, diagnóstico, imagem e
os que vierem depois):

* **401** — sem token, token inválido ou usuário inativo. Resolvido pelo
  fastapi-users (``current_active_user``) antes de qualquer regra de papel/recurso.
* **403** — o papel do usuário não está entre os papéis que a operação aceita.
  É checado antes de tocar no recurso, então não revela nada sobre ele.
* **404** — o papel é aceito, mas o recurso não existe **ou** o usuário não tem
  acesso a ele. Os dois casos respondem igual para impedir enumeração de ids.

  Exceção: ``GET /diagnosticos/{id}`` mantém o contrato anterior ao RBAC —
  diagnóstico inexistente -> 404, existente sem acesso -> **403**.

Admin não herda acesso clínico: cada operação declara explicitamente os papéis que
aceita. ``role``, ``paciente_id``, ``profissional_id`` e ``revisor_id`` vindos do
cliente nunca são prova de acesso — a identidade vem sempre do usuário autenticado
e o vínculo, do banco.

``is_superuser`` não é consultado aqui. Decisão atual: ele vale só para a gestão de
contas do fastapi-users (rotas ``/users/{id}``) e não dá acesso clínico. Unificar
com ``role = admin`` fica para depois.

Valor persistido de ``users.role``: o canônico é o português (``paciente``,
``profissional``, ``admin``, ver ``TipoUsuario``). Os aliases em inglês continuam
aceitos na leitura só por compatibilidade com linhas antigas.

Imagens (``<img>`` não envia Bearer): a resposta de ``GET /diagnosticos/{id}`` traz
cada ``url_arquivo`` já **assinada** (HMAC com ``secret_key``, válida por
``IMAGEM_URL_VALIDADE_SEGUNDOS``). A assinatura só é emitida depois que
``pode_acessar_paciente`` liberou o diagnóstico, então quem recebe a URL já passou
pela regra de acesso. A mesma rota continua aceitando Bearer para chamadas diretas.

Toda decisão é registrada no logger ``app.authz`` (negações em WARNING, permissões
em INFO) com usuário, papel, recurso e correlation id — nunca com payload.
"""

import hashlib
import hmac
import logging
import re
import time
import uuid
from contextvars import ContextVar
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import paciente_profissional_queries
from app.schemas.usuario import TipoUsuario

logger = logging.getLogger("app.authz")

CORRELATION_HEADER = "X-Correlation-ID"

# Definido por `exigir_papeis` no início de cada request protegida e lido por
# `registrar_decisao` — inclusive nas decisões tomadas dentro dos services.
_correlation_id: ContextVar[str | None] = ContextVar("authz_correlation_id", default=None)

# Aceita só ids "bem-comportados" vindos do cliente — evita injeção em log.
_CORRELATION_ID_VALIDO = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

IMAGEM_URL_VALIDADE_SEGUNDOS = 15 * 60

_ALIASES_PAPEL: dict[str, TipoUsuario] = {
    "paciente": TipoUsuario.PACIENTE,
    "patient": TipoUsuario.PACIENTE,
    "profissional": TipoUsuario.PROFISSIONAL,
    "professional": TipoUsuario.PROFISSIONAL,
    "admin": TipoUsuario.ADMIN,
}


class UsuarioAutenticado(Protocol):
    id: uuid.UUID
    role: str


def normalizar_papel(role: str | None) -> TipoUsuario | None:
    """Converte o ``role`` persistido para o papel canônico; desconhecido vira ``None``."""
    if role is None:
        return None

    return _ALIASES_PAPEL.get(role.strip().lower())


def tem_papel(usuario: UsuarioAutenticado, papel: TipoUsuario) -> bool:
    """True se o papel persistido do ``usuario`` corresponde a ``papel`` (aceita aliases)."""
    return normalizar_papel(usuario.role) is papel


def definir_correlation_id(recebido: str | None) -> str:
    """Usa o id enviado pelo cliente se for válido; senão gera um novo."""
    valido = recebido is not None and _CORRELATION_ID_VALIDO.match(recebido)
    correlation_id = recebido if valido else uuid.uuid4().hex
    _correlation_id.set(correlation_id)
    return correlation_id


def registrar_decisao(
    *,
    permitido: bool,
    motivo: str,
    recurso: str,
    usuario: UsuarioAutenticado | None,
) -> None:
    """Loga a decisão de autorização. Recebe só identificadores, nunca payload.

    ``usuario=None`` é o acesso por URL assinada, que não tem usuário na request.
    """
    papel = normalizar_papel(usuario.role) if usuario is not None else None
    campos = {
        "authz_decisao": "permitido" if permitido else "negado",
        "authz_motivo": motivo,
        "authz_recurso": recurso,
        "usuario_id": str(usuario.id) if usuario is not None else "anonimo",
        "papel": papel.value if papel else "desconhecido",
        "correlation_id": _correlation_id.get(),
    }
    logger.log(
        logging.INFO if permitido else logging.WARNING,
        " ".join(f"{chave}={valor}" for chave, valor in campos.items()),
        extra=campos,
    )


async def pode_acessar_paciente(
    db: AsyncSession,
    usuario: UsuarioAutenticado,
    paciente_id: uuid.UUID,
    *,
    recurso: str,
) -> bool:
    """Decide se ``usuario`` pode acessar dados clínicos do ``paciente_id``.

    Paciente só acessa a si mesmo; profissional só acessa pacientes com vínculo
    ativo; qualquer outro papel (inclusive admin) não tem acesso clínico.
    ``recurso`` identifica o que está sendo acessado (ex.: ``"diagnostico:4"``)
    e vai só para o log.
    """
    papel = normalizar_papel(usuario.role)

    if papel is TipoUsuario.PACIENTE:
        permitido = usuario.id == paciente_id
        motivo = "dono" if permitido else "nao_e_dono"
    elif papel is TipoUsuario.PROFISSIONAL:
        permitido = await paciente_profissional_queries.profissional_tem_acesso(
            db,
            paciente_id=paciente_id,
            profissional_id=usuario.id,
        )
        motivo = "vinculo_ativo" if permitido else "sem_vinculo_ativo"
    else:
        permitido = False
        motivo = "papel_sem_acesso_clinico"

    registrar_decisao(permitido=permitido, motivo=motivo, recurso=recurso, usuario=usuario)
    return permitido


def _assinatura_imagem(nome_arquivo: str, expira_em: int) -> str:
    chave = get_settings().secret_key.get_secret_value().encode()
    mensagem = f"imagem:{nome_arquivo}:{expira_em}".encode()
    return hmac.new(chave, mensagem, hashlib.sha256).hexdigest()


def assinar_url_imagem(
    url_arquivo: str,
    *,
    validade_segundos: int = IMAGEM_URL_VALIDADE_SEGUNDOS,
) -> str:
    """Devolve a URL da imagem assinada, para uso direto em ``<img src>``.

    Só pode ser chamada depois de ``pode_acessar_paciente`` liberar o recurso.
    """
    nome_arquivo = url_arquivo.rsplit("/", 1)[-1]
    expira_em = int(time.time()) + validade_segundos
    assinatura = _assinatura_imagem(nome_arquivo, expira_em)
    return f"{url_arquivo}?expira={expira_em}&assinatura={assinatura}"


def url_imagem_assinada_valida(nome_arquivo: str, expira_em: int, assinatura: str) -> bool:
    """Confere a assinatura (tempo constante) e a validade; registra a decisão."""
    if expira_em < time.time():
        permitido, motivo = False, "url_assinada_expirada"
    elif not hmac.compare_digest(_assinatura_imagem(nome_arquivo, expira_em), assinatura):
        permitido, motivo = False, "url_assinada_invalida"
    else:
        permitido, motivo = True, "url_assinada"

    registrar_decisao(
        permitido=permitido, motivo=motivo, recurso=f"imagem:{nome_arquivo}", usuario=None
    )
    return permitido
