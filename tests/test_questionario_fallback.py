import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models import Questionario
from app.services.anamnese_questionary import _QUESTIONARIO_FALLBACK


def _buscar_versao(versao: str) -> Questionario | None:
    async def _buscar() -> Questionario | None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine)() as db:
                return await db.get(Questionario, versao)
        finally:
            await engine.dispose()

    return asyncio.run(_buscar())


def test_versao_de_fallback_esta_persistida_com_o_mesmo_conteudo() -> None:
    persistido = _buscar_versao(_QUESTIONARIO_FALLBACK.versao)

    assert persistido is not None
    # Divergiu: o fallback foi editado sem trocar `versao`.
    assert persistido.perguntas == [
        pergunta.model_dump(mode="json") for pergunta in _QUESTIONARIO_FALLBACK.perguntas
    ]
