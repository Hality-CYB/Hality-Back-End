import uuid

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.policies import pode_acessar_paciente
from app.db import paciente_queries
from app.models.user import User
from app.schemas.paciente import (
    PacienteDetail,
    PacienteListItem,
    PacienteListResponse,
    PacienteVinculo,
)
from app.services import diagnostico_service

ORDENS_LISTAGEM = {"nome_asc"}
LIMITE_MAXIMO = 50
TAMANHO_MAXIMO_BUSCA = 100


class PacienteFiltroInvalidoError(Exception):
    def __init__(self, motivo: str) -> None:
        self.motivo = motivo
        super().__init__(motivo)


class PacienteNaoEncontradoError(Exception):
    pass


def _validar_filtros_listagem(
    busca: str | None,
    pagina: int,
    limite: int,
    ordem: str,
) -> str | None:
    if pagina < 1:
        raise PacienteFiltroInvalidoError("pagina deve ser maior ou igual a 1")

    if limite < 1:
        raise PacienteFiltroInvalidoError("limite deve ser maior ou igual a 1")

    if limite > LIMITE_MAXIMO:
        raise PacienteFiltroInvalidoError(f"limite maximo permitido e {LIMITE_MAXIMO}")

    if ordem not in ORDENS_LISTAGEM:
        raise PacienteFiltroInvalidoError("ordem deve ser nome_asc")

    if busca is None:
        return None

    busca = busca.strip()

    if len(busca) > TAMANHO_MAXIMO_BUSCA:
        raise PacienteFiltroInvalidoError(
            f"busca deve ter no maximo {TAMANHO_MAXIMO_BUSCA} caracteres"
        )

    return busca or None


def _para_item(
    paciente: Row,
    resumo: paciente_queries.ResumoDiagnosticos | None,
) -> PacienteListItem:
    ultimo_nivel = None

    if resumo is not None and resumo.ultimo_status in diagnostico_service.STATUS_COM_RESULTADO:
        ultimo_nivel = resumo.ultimo_nivel

    return PacienteListItem(
        id=paciente.id,
        nome=paciente.name,
        email=paciente.email,
        telefone=paciente.phone,
        ativo=paciente.is_active,
        total_diagnosticos=resumo.total if resumo is not None else 0,
        ultimo_diagnostico_em=resumo.ultimo_em if resumo is not None else None,
        ultimo_nivel=ultimo_nivel,
    )


async def listar_pacientes(
    db: AsyncSession,
    usuario: User,
    busca: str | None = None,
    pagina: int = 1,
    limite: int = 20,
    ordem: str = "nome_asc",
) -> PacienteListResponse:
    busca_normalizada = _validar_filtros_listagem(busca, pagina, limite, ordem)

    resultado = await paciente_queries.listar_pacientes(
        db=db,
        profissional_id=usuario.id,
        busca=busca_normalizada,
        pagina=pagina,
        limite=limite,
    )

    resumos = await paciente_queries.resumir_diagnosticos(
        db,
        [paciente.id for paciente in resultado.itens],
    )

    return PacienteListResponse(
        itens=[_para_item(paciente, resumos.get(paciente.id)) for paciente in resultado.itens],
        pagina=pagina,
        limite=limite,
        total=resultado.total,
        total_paginas=(resultado.total + limite - 1) // limite,
    )


async def obter_paciente(
    db: AsyncSession,
    usuario: User,
    paciente_id: uuid.UUID,
    pagina: int = 1,
    limite: int = 20,
) -> PacienteDetail:
    profissional_id = usuario.id

    # Sem vínculo ativo responde igual a inexistente (404), para não revelar ids.
    if not await pode_acessar_paciente(db, usuario, paciente_id, recurso=f"paciente:{paciente_id}"):
        raise PacienteNaoEncontradoError

    paciente = await paciente_queries.buscar_paciente(db, paciente_id, profissional_id)

    if paciente is None:
        raise PacienteNaoEncontradoError

    try:
        diagnosticos = await diagnostico_service.listar_diagnosticos(
            db=db,
            paciente_id=paciente.id,
            pagina=pagina,
            limite=limite,
        )

    except diagnostico_service.DiagnosticoFiltroInvalidoError as exc:
        raise PacienteFiltroInvalidoError(exc.motivo) from exc

    resumos = await paciente_queries.resumir_diagnosticos(db, [paciente.id])

    vinculos = await paciente_queries.listar_vinculos_do_paciente(
        db,
        paciente.id,
        profissional_id,
    )

    item = _para_item(paciente, resumos.get(paciente.id))

    return PacienteDetail(
        **item.model_dump(),
        vinculos=[
            PacienteVinculo(
                id=vinculo.id,
                profissional_id=vinculo.profissional_id,
                profissional_nome=profissional_nome,
                data_vinculo=vinculo.data_vinculo,
                ativo=vinculo.ativo,
                encerrado_em=vinculo.encerrado_em,
            )
            for vinculo, profissional_nome in vinculos
        ],
        diagnosticos=diagnosticos,
    )
