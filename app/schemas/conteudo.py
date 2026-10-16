import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CategoriaConteudo(StrEnum):
    HIGIENE = "higiene"
    SAUDE = "saude"
    NUTRICAO = "nutricao"
    ROTINA = "rotina"
    ESTILO_DE_VIDA = "estilo_de_vida"
    DIETA = "dieta"
    TRATAMENTO = "tratamento"


class StatusConteudo(StrEnum):
    RASCUNHO = "rascunho"
    PUBLICADO = "publicado"


class DestinoConteudo(StrEnum):
    HOME_AUTENTICADA = "home_autenticada"
    ORIENTACOES_DIAGNOSTICO = "orientacoes_diagnostico"
    CAPTURA = "captura"
    LANDING_PUBLICA = "landing_publica"


class OrdemConteudo(StrEnum):
    ORDEM_ASC = "ordem_asc"
    ORDEM_DESC = "ordem_desc"
    CRIADO_ASC = "created_at_asc"
    CRIADO_DESC = "created_at_desc"


class BlocoConteudo(BaseModel):
    model_config = ConfigDict(extra="allow")

    tipo: str


class ConteudoSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    itens: list[BlocoConteudo] = Field(min_length=1)


def _validar_destinos_classificacoes(
    destinos: list[DestinoConteudo],
    classificacao_ids: list[int],
) -> None:
    if DestinoConteudo.ORIENTACOES_DIAGNOSTICO in destinos and not classificacao_ids:
        raise ValueError("orientacoes_diagnostico exige ao menos uma classificação")

    if DestinoConteudo.CAPTURA in destinos and classificacao_ids:
        raise ValueError("captura não aceita classificação clínica")

    if DestinoConteudo.LANDING_PUBLICA in destinos and classificacao_ids:
        raise ValueError("landing_publica não aceita classificação clínica")


def _validar_url_publica(url: str) -> None:
    if url.startswith("/") and not url.startswith("//"):
        return

    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL inválida para conteúdo público")


def _validar_conteudo_publico(conteudo: ConteudoSchema) -> None:
    for bloco in conteudo.itens:
        dados = bloco.model_dump()
        tipo = bloco.tipo

        if tipo == "texto":
            if set(dados) != {"tipo", "texto"}:
                raise ValueError("bloco texto público possui campos não permitidos")

            texto = dados.get("texto")

            if not isinstance(texto, str) or not texto.strip():
                raise ValueError("bloco texto público exige texto")

            if "<" in texto or ">" in texto:
                raise ValueError("HTML não é permitido em conteúdo público")

        elif tipo == "imagem":
            if set(dados) != {"tipo", "url", "alt"}:
                raise ValueError("bloco imagem público possui campos não permitidos")

            url = dados.get("url")
            alt = dados.get("alt")

            if not isinstance(url, str) or not url.strip():
                raise ValueError("bloco imagem público exige URL")

            if not isinstance(alt, str) or not alt.strip():
                raise ValueError("bloco imagem público exige texto alternativo")

            _validar_url_publica(url)

        else:
            raise ValueError(f"tipo de bloco não permitido em conteúdo público: {tipo}")


class ConteudoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titulo: str = Field(min_length=1, max_length=255)

    categoria: CategoriaConteudo

    conteudo: ConteudoSchema

    classificacao_ids: list[int] = Field(default_factory=list)

    destinos: list[DestinoConteudo] = Field(default_factory=list)

    aparece_na_home: bool = Field(
        default=False,
        deprecated=True,
        description=("Campo legado. Use o destino home_autenticada em destinos."),
    )

    status: StatusConteudo = StatusConteudo.RASCUNHO

    ordem: int = Field(default=0, ge=0)

    @field_validator("classificacao_ids")
    @classmethod
    def _deduplicar_classificacoes(cls, valor: list[int]) -> list[int]:
        return list(dict.fromkeys(valor))

    @field_validator("destinos")
    @classmethod
    def _deduplicar_destinos(
        cls,
        valor: list[DestinoConteudo],
    ) -> list[DestinoConteudo]:
        return list(dict.fromkeys(valor))

    @model_validator(mode="after")
    def _validar_destinos(self):
        _validar_destinos_classificacoes(
            self.destinos,
            self.classificacao_ids,
        )

        if DestinoConteudo.LANDING_PUBLICA in self.destinos:
            _validar_conteudo_publico(self.conteudo)

        return self


class ConteudoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titulo: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )

    categoria: CategoriaConteudo | None = None

    conteudo: ConteudoSchema | None = None

    classificacao_ids: list[int] | None = None

    destinos: list[DestinoConteudo] | None = None

    aparece_na_home: bool | None = Field(
        default=None,
        deprecated=True,
        description=("Campo legado. Use o destino home_autenticada em destinos."),
    )

    status: StatusConteudo | None = None

    ordem: int | None = Field(default=None, ge=0)

    @field_validator("classificacao_ids")
    @classmethod
    def _deduplicar_classificacoes(cls, valor: list[int]) -> list[int]:
        return list(dict.fromkeys(valor))

    @field_validator("destinos")
    @classmethod
    def _deduplicar_destinos(
        cls,
        valor: list[DestinoConteudo],
    ) -> list[DestinoConteudo]:
        return list(dict.fromkeys(valor))

    @field_validator("*", mode="before")
    @classmethod
    def _nao_aceita_nulo(cls, valor: Any) -> Any:
        # Update parcial: campo omitido não muda nada, mas `null` explícito
        # gravaria NULL em coluna NOT NULL (500). Todos os campos são obrigatórios
        # no banco, então nenhum aceita nulo.
        if valor is None:
            raise ValueError("não pode ser nulo")

        return valor

    @model_validator(mode="after")
    def _validar_destinos(self):
        # No PATCH nem sempre temos informação suficiente para validar o estado
        # final. O service complementa esta validação usando o registro atual.
        if self.destinos is not None and self.classificacao_ids is not None:
            _validar_destinos_classificacoes(
                self.destinos,
                self.classificacao_ids,
            )

        if (
            self.destinos is not None
            and DestinoConteudo.LANDING_PUBLICA in self.destinos
            and self.conteudo is not None
        ):
            _validar_conteudo_publico(self.conteudo)

        return self


class ConteudoDetail(ConteudoCreate):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int

    created_at: datetime

    updated_at: datetime

    criado_por_id: uuid.UUID | None

    atualizado_por_id: uuid.UUID | None

    publicado_por_id: uuid.UUID | None

    publicado_em: datetime | None


class ConteudoListResponse(BaseModel):
    items: list[ConteudoDetail]

    total: int

    page: int

    limit: int

    has_next: bool
