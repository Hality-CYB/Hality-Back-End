import uuid

from app.schemas.anamnese import AnamneseCreate, AnamneseCreated, AnamneseDetail
from app.services.anamnese_lexer import AnamneseValidationError, lexar_respostas
from app.services.anamnese_questionary import get_questionario_ativo
from app.services.anamnese_store import AnamneseRecord, AnamneseRepository
from app.services.atendimento_service import (
    AtorAutenticado,
    AtorNaoProfissionalError,
    resolver_titular,
)

__all__ = [
    "AnamneseValidationError",
    "AnamneseNaoEncontradaError",
    "criar_anamnese",
    "criar_anamnese_para_paciente",
    "listar_anamneses",
    "obter_anamnese",
    "atualizar_anamnese",
    "deletar_anamnese",
]


class AnamneseNaoEncontradaError(Exception):
    pass


def _para_detalhe(registro: AnamneseRecord) -> AnamneseDetail:
    return AnamneseDetail(
        id=registro.id_resp,
        paciente_id=registro.paciente_id,
        data_preenchimento=registro.data_preenchimento,
        versao_questionario=registro.id_versao_questionario,
        respostas=registro.respostas,
    )


async def criar_anamnese(
    repo: AnamneseRepository,
    paciente_id: uuid.UUID,
    payload: AnamneseCreate,
    executor_id: uuid.UUID | None = None,
) -> AnamneseCreated:
    """Sem `executor_id`, é autoavaliação: o próprio titular é o executor."""
    questionario = await get_questionario_ativo(repo.db)
    respostas_lexadas = lexar_respostas(questionario, payload)
    registro = await repo.salvar(
        paciente_id=paciente_id,
        id_versao_questionario=payload.versao_questionario,
        respostas=respostas_lexadas,
        executor_id=executor_id or paciente_id,
    )
    return AnamneseCreated(
        id=registro.id_resp,
        paciente_id=registro.paciente_id,
        data_preenchimento=registro.data_preenchimento,
    )


async def criar_anamnese_para_paciente(
    repo: AnamneseRepository,
    ator: AtorAutenticado,
    paciente_id: uuid.UUID,
    payload: AnamneseCreate,
) -> AnamneseCreated:
    """Profissional preenchendo a anamnese de um paciente vinculado.

    O vínculo é validado antes de ler o questionário ou persistir qualquer
    coisa — erros de `atendimento_service` sobem sem efeito colateral.
    """
    if not ator.eh_profissional:
        raise AtorNaoProfissionalError
    titular = await resolver_titular(repo.db, ator, paciente_id)
    return await criar_anamnese(repo, titular, payload, executor_id=ator.id)


async def listar_anamneses(
    repo: AnamneseRepository, paciente_id: uuid.UUID
) -> list[AnamneseDetail]:
    registros = await repo.listar_por_paciente(paciente_id)
    return [_para_detalhe(r) for r in registros]


async def obter_anamnese(
    repo: AnamneseRepository, paciente_id: uuid.UUID, id_resp: int
) -> AnamneseDetail:
    registro = await repo.obter_por_id(id_resp)
    if registro is None or registro.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError
    return _para_detalhe(registro)


async def atualizar_anamnese(
    repo: AnamneseRepository, paciente_id: uuid.UUID, id_resp: int, payload: AnamneseCreate
) -> AnamneseDetail:
    registro = await repo.obter_por_id(id_resp)
    if registro is None or registro.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError
    questionario = await get_questionario_ativo(repo.db)
    respostas_lexadas = lexar_respostas(questionario, payload)
    atualizado = await repo.atualizar(
        id_resp=id_resp,
        id_versao_questionario=payload.versao_questionario,
        respostas=respostas_lexadas,
    )
    if atualizado is None:
        raise AnamneseNaoEncontradaError
    return _para_detalhe(atualizado)


async def deletar_anamnese(repo: AnamneseRepository, paciente_id: uuid.UUID, id_resp: int) -> None:
    registro = await repo.obter_por_id(id_resp)
    if registro is None or registro.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError
    await repo.deletar(id_resp)
