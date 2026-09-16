"""Modelo de refresh token — sessão persistida em banco para renovação do access token."""

import uuid

# Precisa ser importado antes de `fastapi_users_db_sqlalchemy.access_token`
# abaixo: `fastapi_users.db` tenta reexportar nomes de
# `fastapi_users_db_sqlalchemy` no seu próprio __init__, e se
# `fastapi_users_db_sqlalchemy` for tocado primeiro por um import de
# submódulo (como o de `access_token` logo abaixo), as duas libs entram
# num ciclo de inicialização parcial — o `except ImportError` interno da
# lib engole o erro, e `fastapi_users.db.SQLAlchemyBaseUserTableUUID` (usado
# por `app/models/user.py`) fica ausente pro resto do processo. Forçar essa
# inicialização aqui primeiro evita o ciclo, independente da ordem de
# import em `app/models/__init__.py`.
import fastapi_users.db  # noqa: F401
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTable
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RefreshToken(SQLAlchemyBaseAccessTokenTable[uuid.UUID], Base):
    """Tabela ``refresh_tokens``: token opaco usado só por ``POST /auth/refresh``.

    Nunca é enviado em nenhuma outra rota — o access token (JWT, curto) é
    quem autentica as chamadas normais. Cada refresh é rotacionado: o token
    usado é apagado e um novo é emitido, então reapresentar um já usado é
    sinal de token roubado.

    Campos herdados de ``SQLAlchemyBaseAccessTokenTable``: ``token`` (string
    aleatória, indexada e única) e ``created_at`` (usado pela
    ``DatabaseStrategy`` para calcular expiração via ``lifetime_seconds``).

    ``user_id`` é redeclarado à mão em vez de usar o mixin
    ``...TableUUID`` pronto do fastapi-users-db-sqlalchemy: aquele mixin
    fixa a FK em ``user.id`` (singular), mas a tabela de usuários deste
    projeto é ``users`` (ver ``app/models/user.py``).
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="cascade"), nullable=False
    )
