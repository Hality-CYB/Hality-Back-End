from fastapi import APIRouter, Response

from app.api.deps import DbSession
from app.db import conteudo_queries
from app.schemas.conteudo import DestinoConteudo

router = APIRouter(
    prefix="/public",
    tags=["conteudos-publicos"],
)


@router.get("/landing")
async def listar_conteudos_landing(
    db: DbSession,
    response: Response,
) -> list[dict]:
    conteudos = await conteudo_queries.listar_publicados_por_destino(
        db,
        DestinoConteudo.LANDING_PUBLICA,
    )

    response.headers["Cache-Control"] = "public, max-age=300"

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
