from app.schemas.anamnese import Pergunta, Questionario, TipoPergunta

# Catálogo estático do questionário ativo. Isolado nesse módulo pra ser fácil
# de trocar por uma fonte real (admin/CMS/banco) quando ela existir, sem
# precisar mexer no service, no lexer ou nos endpoints - o contrato
# (Questionario/Pergunta) é o mesmo nos dois casos.
# A ideia é servir de fallback caso o banco falhe ou tenha algum problema,
# garantindo que a aplicação não quebre por falta de uma fonte de dados real.
_QUESTIONARIO_ATIVO = Questionario(
    versao="2026-09-v1",
    perguntas=[
        Pergunta(
            id="higiene_bucal",
            enunciado="Classifique sua higiene bucal",
            tipo=TipoPergunta.SCALE,
            obrigatoria=True,
            escala_min=1,
            escala_max=5,
            escala_label_min="Ruim",
            escala_label_max="Excelente",
        ),
        Pergunta(
            id="medicacao_regular",
            enunciado="Você usa alguma medicação regularmente?",
            tipo=TipoPergunta.TEXT,
            obrigatoria=True,
        ),
        Pergunta(
            id="fumante",
            enunciado="Você é fumante?",
            tipo=TipoPergunta.BOOLEAN,
            obrigatoria=True,
        ),
        Pergunta(
            id="frequencia_escovacao",
            enunciado="Com que frequência escova os dentes?",
            tipo=TipoPergunta.SINGLE_CHOICE,
            obrigatoria=True,
            opcoes=["1x ao dia", "2x ao dia", "3x ao dia", "Mais de 3x ao dia"],
        ),
    ],
)


def get_questionario_ativo() -> Questionario:
    return _QUESTIONARIO_ATIVO