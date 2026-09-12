from app.db.anamnese_store import AnamneseRecord, AnamneseRepository
from app.schemas.anamnese import AnamneseCreate, AnamneseCreated, AnamneseDetail
from app.services.anamnese_lexer import AnamneseValidationError, lexar_respostas
from app.services.anamnese_questionary import get_questionario_ativo

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
        id_resp=registro.id_resp,
        paciente_id=registro.paciente_id,
        data_preenchimento=registro.data_preenchimento,
        id_versao_questionario=registro.id_versao_questionario,
        respostas=registro.respostas,
    )


async def criar_anamnese(
    db: AsyncSession, paciente_id: int, payload: AnamneseCreate
) -> AnamneseCreated:
    respostas_lexadas = lexar_respostas(get_questionario_ativo(), payload)
    registro = repo.salvar(
        paciente_id=paciente_id,
        id_versao_questionario=payload.id_versao_questionario,
        respostas=respostas_lexadas,
    )
    return AnamneseCreated(
        id_resp=registro.id_resp,
        paciente_id=registro.paciente_id,
        data_preenchimento=registro.data_preenchimento,
    )


async def listar_anamneses(db: AsyncSession, paciente_id: int) -> list[AnamneseDetail]:
    anamneses = await anamnese_queries.listar_por_paciente(db, paciente_id)
    return [_para_detalhe(a) for a in anamneses]


def obter_anamnese(repo: AnamneseRepository, paciente_id: int, id_resp: int) -> AnamneseDetail:
    registro = repo.obter_por_id(id_resp)
    if registro is None or registro.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError
    return _para_detalhe(anamnese)


def atualizar_anamnese(
    repo: AnamneseRepository, paciente_id: int, id_resp: int, payload: AnamneseCreate
) -> AnamneseDetail:
    registro = repo.obter_por_id(id_resp)
    if registro is None or registro.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError
    respostas_lexadas = lexar_respostas(get_questionario_ativo(), payload)
    atualizado = repo.atualizar(
        id_resp=id_resp,
        id_versao_questionario=payload.id_versao_questionario,
        respostas=respostas_lexadas,
    )
    return _para_detalhe(anamnese)


def deletar_anamnese(repo: AnamneseRepository, paciente_id: int, id_resp: int) -> None:
    registro = repo.obter_por_id(id_resp)
    if registro is None or registro.paciente_id != paciente_id:
        raise AnamneseNaoEncontradaError
    repo.deletar(id_resp)
