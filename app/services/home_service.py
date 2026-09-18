from sqlalchemy.ext.asyncio import AsyncSession

from app.db import diagnostico_queries, home_queries
from app.models.diagnostico import Diagnostico
from app.models.user import User
from app.schemas.home import (
    HomeClassificacao,
    HomeDica,
    HomeResponse,
    HomeUltimoDiagnostico,
    HomeUsuario,
)

STATUS_COM_RESULTADO = {"aguardando_revisao", "concluido"}


async def _montar_ultimo_diagnostico(
    db: AsyncSession, diagnostico: Diagnostico
) -> HomeUltimoDiagnostico:
    classificacao = None

    if diagnostico.status in STATUS_COM_RESULTADO and diagnostico.classificacao_id is not None:
        classificacao_model = await diagnostico_queries.buscar_classificacao(
            db, diagnostico.classificacao_id
        )
        if classificacao_model is not None:
            classificacao = HomeClassificacao(
                codigo=classificacao_model.codigo,
                nome_exibicao=classificacao_model.nome_exibicao,
            )

    return HomeUltimoDiagnostico(
        id=diagnostico.id,
        data_diagnostico=diagnostico.data_diagnostico,
        status=diagnostico.status,
        classificacao=classificacao,
        escala_saburra=(
            diagnostico.escala_saburra
            if diagnostico.status in STATUS_COM_RESULTADO
            else None
        ),
    )


async def montar_home(db: AsyncSession, usuario: User) -> HomeResponse:
    diagnostico = await home_queries.buscar_ultimo_diagnostico(db, usuario.id)
    dicas = await home_queries.listar_dicas_home(db)

    ultimo_diagnostico = None
    if diagnostico is not None:
        ultimo_diagnostico = await _montar_ultimo_diagnostico(db, diagnostico)

    return HomeResponse(
        usuario=HomeUsuario(id=usuario.id, nome=usuario.name, tipo_usuario=usuario.role),
        ultimo_diagnostico=ultimo_diagnostico,
        dicas=[
            HomeDica(
                id=dica.id,
                titulo=dica.titulo,
                categoria=dica.categoria,
                conteudo=dica.conteudo,
            )
            for dica in dicas
        ],
    )
