from sqlalchemy.ext.asyncio import AsyncSession

from app.db import diagnostico_queries, home_queries
from app.models.diagnostico import Diagnostico
from app.models.user import User
from app.schemas.home import (
    DicaResumo,
    HomeClassificacao,
    HomeResponse,
    HomeUltimoDiagnostico,
    HomeUsuario,
)

# TODO(avisos): substituir por contagem real quando o domínio de avisos
# (avisos_atualizacoes/usuario_avisos) existir no projeto.
AVISOS_NAO_LIDOS_PLACEHOLDER = 0

DICAS_HOME_LIMIT = 3


async def _montar_ultimo_diagnostico(
    db: AsyncSession, diagnostico: Diagnostico
) -> HomeUltimoDiagnostico:
    classificacao = None

    if diagnostico.classificacao_id is not None:
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
        escala_saburra=diagnostico.escala_saburra,
    )


async def montar_home(db: AsyncSession, usuario: User) -> HomeResponse:
    total_diagnosticos = await home_queries.contar_diagnosticos(db, usuario.id)
    diagnostico = await home_queries.buscar_ultimo_diagnostico(db, usuario.id)
    total_dicas = await home_queries.contar_dicas(db)
    dicas = await home_queries.listar_dicas(db, DICAS_HOME_LIMIT)

    ultimo_diagnostico = None
    if diagnostico is not None:
        ultimo_diagnostico = await _montar_ultimo_diagnostico(db, diagnostico)

    return HomeResponse(
        usuario=HomeUsuario(id=usuario.id, nome=usuario.name, tipo_usuario=usuario.role),
        total_diagnosticos=total_diagnosticos,
        avisos_nao_lidos=AVISOS_NAO_LIDOS_PLACEHOLDER,
        ultimo_diagnostico=ultimo_diagnostico,
        total_dicas=total_dicas,
        dicas=[
            DicaResumo(id=dica.id, titulo=dica.titulo, conteudo=dica.conteudo) for dica in dicas
        ],
    )
