import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.questionario import Questionario as QuestionarioOrm
from app.schemas.anamnese import Pergunta, Questionario, TipoPergunta

logger = logging.getLogger(__name__)

# Catálogo estático do questionário ativo. Isolado nesse módulo pra ser fácil
# de trocar por uma fonte real (admin/CMS/banco) quando ela existir, sem
# precisar mexer no service, no lexer ou nos endpoints - o contrato
# (Questionario/Pergunta) é o mesmo nos dois casos.
# É o fallback usado quando a tabela `questionarios` está vazia ou a consulta
# falha, garantindo que a aplicação não quebre por falta de uma fonte de
# dados real.
_QUESTIONARIO_FALLBACK = Questionario(
    versao="2026-08-v1",
    perguntas=[
        Pergunta(
            id="mau_halito_ao_acordar",
            enunciado="Você sente mau hálito ao acordar?",
            tipo=TipoPergunta.BOOLEAN,
            obrigatoria=True,
        ),
        Pergunta(
            id="frequencia_escovacao",
            enunciado="Com que frequência você escova os dentes?",
            tipo=TipoPergunta.SINGLE_CHOICE,
            obrigatoria=True,
            opcoes=["1x ao dia", "2x ao dia", "3x ou mais"],
        ),
        Pergunta(
            id="sintomas_adicionais",
            enunciado="Descreva sintomas adicionais, se houver.",
            tipo=TipoPergunta.TEXT,
            obrigatoria=False,
        ),
        Pergunta(
            id="avaliacao_propria_halito",
            enunciado="Como você avalia o cheiro da sua respiração?",
            tipo=TipoPergunta.SCALE,
            obrigatoria=True,
            escala_min=1,
            escala_max=5,
            escala_label_min="Ruim",
            escala_label_max="Excelente",
        ),
    ],
)


async def get_questionario_ativo(db: AsyncSession) -> Questionario:
    """Busca a versão vigente do questionário na tabela `questionarios`
    (a de `criado_em` mais recente). Se a tabela estiver vazia ou a consulta
    falhar por qualquer motivo, cai pro catálogo estático (`_QUESTIONARIO_FALLBACK`)
    em vez de propagar o erro - o preenchimento da anamnese não pode ficar
    fora do ar por causa disso."""

    try:
        resultado = await db.execute(
            select(QuestionarioOrm).order_by(QuestionarioOrm.criado_em.desc()).limit(1)
        )
        orm = resultado.scalar_one_or_none()
    except Exception:
        logger.exception("Falha ao buscar questionário vigente no banco, usando fallback estático.")
        await db.rollback()
        return _QUESTIONARIO_FALLBACK

    if orm is None:
        return _QUESTIONARIO_FALLBACK

    return Questionario.model_validate({"versao": orm.versao, "perguntas": orm.perguntas})
