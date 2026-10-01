import uuid

from app.auth.policies import UsuarioAutenticado, pode_acessar_paciente
from app.schemas.anamnese import AnamneseCreate, AnamneseCreated, AnamneseDetail
from app.services.anamnese_lexer import AnamneseValidationError, lexar_respostas
from app.services.anamnese_questionary import get_questionario_ativo
from app.services.anamnese_store import AnamneseRecord, AnamneseRepository

__all__ = [
    "AnamneseValidationError",
    "AnamneseNaoEncontradaError",
    "criar_anamnese",
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
    repo: AnamneseRepository, paciente_id: uuid.UUID, payload: AnamneseCreate
) -> AnamneseCreated:
    questionario = await get_questionario_ativo(repo.db)
    respostas_lexadas = lexar_respostas(questionario, payload)
    registro = await repo.salvar(
        paciente_id=paciente_id,
        id_versao_questionario=payload.versao_questionario,
        respostas=respostas_lexadas,
    )
    return AnamneseCreated(
        id=registro.id_resp,
        paciente_id=registro.paciente_id,
        data_preenchimento=registro.data_preenchimento,
    )


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
