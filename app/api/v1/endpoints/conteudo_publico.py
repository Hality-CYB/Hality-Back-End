from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import FileResponse

from app.api.deps import DbSession
from app.db import conteudo_queries
from app.schemas.conteudo import DestinoConteudo
from app.services import conteudo_storage

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


@router.get("/conteudos/midias/{nome_arquivo}", include_in_schema=False)
async def obter_midia(nome_arquivo: str) -> FileResponse:
    """Imagem ou vídeo de um conteúdo.

    Aberta, sem login: conteúdo educativo não é dado de paciente, e assim
    `<img>` e `<video>` carregam sem token. O `FileResponse` atende pedidos por
    faixa (Range), então o vídeo avança e volta sem baixar tudo.
    """
    caminho = conteudo_storage.resolver_caminho(nome_arquivo)

    if caminho is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="mídia não encontrada",
        )

    return FileResponse(caminho)
