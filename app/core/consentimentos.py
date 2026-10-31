"""Catálogo versionado de consentimentos por finalidade (US-020).

Única fonte dos textos e versões apresentados ao titular: endpoints e serviços
só referenciam este catálogo, nunca embutem copy jurídica. Para publicar uma
versão nova de um termo, troque ``versao`` (e o ``texto``) aqui — quem já
decidiu na versão anterior passa a ``requer_decisao`` até decidir de novo.

ATENÇÃO: os textos abaixo são um RASCUNHO escrito pelo time a partir do que o
app faz hoje. A redação final depende da aprovação do jurídico/Hality (OPEN-06),
e os trechos entre colchetes precisam ser preenchidos antes de ir para produção.
Como nada foi a produção ainda, a versão continua "v1".
"""

from dataclasses import dataclass
from enum import StrEnum


class Finalidade(StrEnum):
    HEALTH_DATA = "health_data"
    IMAGE_TRAINING = "image_training"


class OrigemConsentimento(StrEnum):
    """Fluxo em que a decisão foi coletada."""

    REGISTRO = "registro"
    CONVITE = "convite"
    GOOGLE = "google"
    PERFIL = "perfil"


@dataclass(frozen=True, slots=True)
class TermoConsentimento:
    finalidade: Finalidade
    versao: str
    obrigatorio: bool
    titulo: str
    texto: str


# Uma linha por item da tupla; o front mostra o texto com as quebras de linha.
_TEXTO_DADOS_DE_SAUDE = "\n".join(
    (
        "Para gerar o seu pré-diagnóstico de halitose, o Check Your Breath precisa tratar "
        "dados pessoais sensíveis sobre a sua saúde. Ao marcar esta opção, você dá o seu "
        "consentimento específico e destacado para esse tratamento, conforme o art. 11, "
        "inciso I, da Lei Geral de Proteção de Dados (Lei nº 13.709/2018).",
        "",
        "Quais dados",
        "- As respostas da anamnese (hábitos de higiene, saúde bucal e sintomas).",
        "- As fotos da sua língua enviadas para análise.",
        "- O resultado do pré-diagnóstico gerado pela inteligência artificial e as revisões "
        "feitas por profissionais de saúde.",
        "",
        "Para que",
        "- Gerar o pré-diagnóstico e as orientações para o seu nível de hálito.",
        "- Permitir que o profissional de saúde vinculado a você revise o resultado.",
        "- Guardar o seu histórico para você acompanhar a evolução.",
        "",
        "Quem tem acesso",
        "Você, os profissionais de saúde vinculados à sua conta e a equipe autorizada da "
        "Hality Diagnóstico do Hálito, que acessa os dados só quando necessário para operar "
        "e dar suporte ao serviço. Os seus dados de saúde não são vendidos nem usados para "
        "publicidade.",
        "",
        "O pré-diagnóstico é uma triagem feita por inteligência artificial e não substitui a "
        "avaliação de um profissional de saúde.",
        "",
        "Este consentimento é obrigatório para usar o app, porque sem esses dados não é "
        "possível fazer o pré-diagnóstico. Você pode revogá-lo a qualquer momento em Perfil > "
        "Privacidade. Depois da revogação, não será possível fazer novos diagnósticos, e o "
        "que já foi feito continua guardado pelo prazo descrito na Política de Privacidade.",
        "",
        "Dúvidas ou pedidos sobre os seus dados: [e-mail do encarregado de dados].",
    )
)

_TEXTO_TREINAMENTO_DE_IMAGEM = "\n".join(
    (
        "Esta autorização é opcional. Se você não marcar, o app funciona exatamente do mesmo "
        "jeito.",
        "",
        "Ao marcar esta opção, você autoriza a Hality Diagnóstico do Hálito a usar as fotos da "
        "sua língua enviadas no app, junto com o resultado do pré-diagnóstico e da revisão do "
        "profissional, para treinar e avaliar o modelo de inteligência artificial que faz a "
        "análise.",
        "",
        "Como as fotos são usadas",
        "- Antes de entrar na base de treinamento, as fotos são separadas do seu nome, e-mail, "
        "telefone e respostas da anamnese.",
        "- Elas são usadas só para melhorar a precisão do pré-diagnóstico.",
        "- Não são publicadas, vendidas nem usadas em publicidade.",
        "",
        "Você pode revogar esta autorização a qualquer momento em Perfil > Privacidade. A "
        "partir da revogação, as suas fotos não entram em novos treinamentos. [Definir com o "
        "jurídico/Hality: o que acontece com fotos já usadas em treinamentos anteriores.]",
        "",
        "Dúvidas ou pedidos sobre os seus dados: [e-mail do encarregado de dados].",
    )
)


TERMOS: dict[Finalidade, TermoConsentimento] = {
    Finalidade.HEALTH_DATA: TermoConsentimento(
        finalidade=Finalidade.HEALTH_DATA,
        versao="v1",
        obrigatorio=True,
        titulo="Tratamento de dados de saúde",
        texto=_TEXTO_DADOS_DE_SAUDE,
    ),
    Finalidade.IMAGE_TRAINING: TermoConsentimento(
        finalidade=Finalidade.IMAGE_TRAINING,
        versao="v1",
        obrigatorio=False,
        titulo="Uso da imagem para treinamento",
        texto=_TEXTO_TREINAMENTO_DE_IMAGEM,
    ),
}


def termo_vigente(finalidade: Finalidade) -> TermoConsentimento:
    return TERMOS[finalidade]
