from fastapi import APIRouter

from app.api.deps import CurrentClinicalUser, DbSession
from app.db import conteudo_queries
from app.schemas.conteudo import DestinoConteudo

router = APIRouter(
    prefix="/conteudos",
    tags=["conteudos"],
)


@router.get("/captura")
async def listar_conteudos_captura(
    _usuario: CurrentClinicalUser,
    db: DbSession,
) -> list[dict]:
    conteudos = await conteudo_queries.listar_publicados_por_destino(
        db,
        DestinoConteudo.CAPTURA,
    )

    return [
        {
            "id": conteudo.id,
            "titulo": conteudo.titulo,
            "categoria": conteudo.categoria,
            "conteudo": conteudo.conteudo,
            "ordem": conteudo.ordem,
        }
        for conteudo in conteudos
    ]