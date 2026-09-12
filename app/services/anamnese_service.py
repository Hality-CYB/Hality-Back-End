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
    repo: AnamneseRepository, paciente_id: int, payload: AnamneseCreate
) -> AnamneseCreated:
    respostas_lexadas = lexar_respostas(get_questionario_ativo(), payload)
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


async def listar_anamneses(repo: AnamneseRepository, paciente_id: int) -> list[AnamneseDetail]:
    registros = await repo.listar_por_paciente(paciente_id)
    registros.sort(key=lambda r: r.data_preenchimento, reverse=True)
    return [_para_detalhe(r) for r in registros]


async def obter_anamnese(
    repo: AnamneseRepository, paciente_id: int, id_resp: int
) -> AnamneseDetail:
    registro = await repo.obter_por_id(id_resp)
    if registro is None or registro.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError
    return _para_detalhe(registro)


async def atualizar_anamnese(
    repo: AnamneseRepository, paciente_id: int, id_resp: int, payload: AnamneseCreate
) -> AnamneseDetail:
    registro = await repo.obter_por_id(id_resp)
    if registro is None or registro.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError
    respostas_lexadas = lexar_respostas(get_questionario_ativo(), payload)
    atualizado = await repo.atualizar(
        id_resp=id_resp,
        id_versao_questionario=payload.versao_questionario,
        respostas=respostas_lexadas,
    )
    if atualizado is None:
        raise AnamneseNaoEncontradaError
    return _para_detalhe(atualizado)


async def deletar_anamnese(repo: AnamneseRepository, paciente_id: int, id_resp: int) -> None:
    registro = await repo.obter_por_id(id_resp)
    if registro is None or registro.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError
    await repo.deletar(id_resp)
