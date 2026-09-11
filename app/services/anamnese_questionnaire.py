from app.schemas.anamnese import Pergunta, Questionario, TipoPergunta

# Catálogo estático do questionário ativo. Isolado nesse módulo para ser fácil
# de trocar por uma fonte real (admin/CMS/banco) quando ela existir, sem
# precisar mexer no service ou nos endpoints.
_QUESTIONARIO_ATIVO = Questionario(
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


def get_questionario_ativo() -> Questionario:
    return _QUESTIONARIO_ATIVO
