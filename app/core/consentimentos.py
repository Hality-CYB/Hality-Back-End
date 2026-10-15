"""Catálogo versionado de consentimentos por finalidade (US-020).

Única fonte dos textos e versões apresentados ao titular: endpoints e serviços
só referenciam este catálogo, nunca embutem copy jurídica. Para publicar uma
versão nova de um termo, troque ``versao`` (e o ``texto``) aqui — quem já
decidiu na versão anterior passa a ``requer_decisao`` até decidir de novo.

ATENÇÃO: os textos abaixo são PROVISÓRIOS. A redação final depende da aprovação
do jurídico/Hality (OPEN-06) e deve substituir estes placeholders antes de ir
para produção.
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


TERMOS: dict[Finalidade, TermoConsentimento] = {
    Finalidade.HEALTH_DATA: TermoConsentimento(
        finalidade=Finalidade.HEALTH_DATA,
        versao="v1",
        obrigatorio=True,
        titulo="Tratamento de dados de saúde",
        texto="[TEXTO PROVISÓRIO — aguardando aprovação jurídica (OPEN-06)]",
    ),
    Finalidade.IMAGE_TRAINING: TermoConsentimento(
        finalidade=Finalidade.IMAGE_TRAINING,
        versao="v1",
        obrigatorio=False,
        titulo="Uso da imagem para treinamento",
        texto="[TEXTO PROVISÓRIO — aguardando aprovação jurídica (OPEN-06)]",
    ),
}


def termo_vigente(finalidade: Finalidade) -> TermoConsentimento:
    return TERMOS[finalidade]
