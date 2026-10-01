import uuid

from app.auth.policies import UsuarioAutenticado, pode_acessar_paciente
from app.db import user_queries
from app.schemas.anamnese import AnamneseCreate, AnamneseCreated, AnamneseDetail
from app.services.anamnese_lexer import AnamneseValidationError, lexar_respostas
from app.services.anamnese_questionary import get_questionario_ativo
from app.services.anamnese_store import AnamneseRecord, AnamneseRepository

__all__ = [
    "AnamneseValidationError",
    "AnamneseNaoEncontradaError",
    "PacienteNaoEncontradoError",
    "criar_anamnese",
    "criar_anamnese_para_paciente",
    "listar_anamneses",
    "obter_anamnese",
    "atualizar_anamnese",
    "deletar_anamnese",
]


class AnamneseNaoEncontradaError(Exception):
    pass


class PacienteNaoEncontradoError(Exception):
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
    profissional: UsuarioAutenticado,
    paciente_id: uuid.UUID,
    payload: AnamneseCreate,
) -> AnamneseCreated:
    """Profissional preenchendo a anamnese de um paciente vinculado (US-090).

    O acesso é checado antes de ler o questionário ou gravar qualquer coisa.
    Sem vínculo ativo, ou paciente inativo, responde igual a inexistente (404).
    """
    if not await pode_acessar_paciente(
        repo.db, profissional, paciente_id, recurso=f"paciente:{paciente_id}"
    ):
        raise PacienteNaoEncontradoError

    paciente = await user_queries.buscar_usuario(repo.db, paciente_id)
    if paciente is None or not paciente.is_active:
        raise PacienteNaoEncontradoError

    return await criar_anamnese(repo, paciente_id, payload, executor_id=profissional.id)


async def listar_anamneses(
    repo: AnamneseRepository, paciente_id: uuid.UUID
) -> list[AnamneseDetail]:
    registros = await repo.listar_por_paciente(paciente_id)
    return [_para_detalhe(r) for r in registros]


async def _buscar_com_acesso(
    repo: AnamneseRepository, usuario: UsuarioAutenticado, id_resp: int
) -> AnamneseRecord:
    registro = await repo.obter_por_id(id_resp)
    # Sem acesso responde igual a inexistente (404) para não permitir enumeração.
    if registro is None or not await pode_acessar_paciente(
        repo.db, usuario, registro.paciente_id, recurso=f"anamnese:{id_resp}"
    ):
        raise AnamneseNaoEncontradaError
    return registro


async def obter_anamnese(
    repo: AnamneseRepository, usuario: UsuarioAutenticado, id_resp: int
) -> AnamneseDetail:
    registro = await _buscar_com_acesso(repo, usuario, id_resp)
    return _para_detalhe(registro)


async def atualizar_anamnese(
    repo: AnamneseRepository,
    usuario: UsuarioAutenticado,
    id_resp: int,
    payload: AnamneseCreate,
) -> AnamneseDetail:
    await _buscar_com_acesso(repo, usuario, id_resp)
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


async def deletar_anamnese(
    repo: AnamneseRepository, usuario: UsuarioAutenticado, id_resp: int
) -> None:
    await _buscar_com_acesso(repo, usuario, id_resp)
    await repo.deletar(id_resp)
