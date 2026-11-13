import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.policies import tem_papel
from app.core.consentimentos import Finalidade
from app.db import auditoria_queries
from app.models.classificacao_diagnostico import ClassificacaoDiagnostico
from app.models.diagnostico import Diagnostico
from app.models.imagem import Imagem
from app.models.rotulo_dataset import RotuloDataset
from app.models.user import User
from app.schemas.diagnostico import ClassificacaoDiagnosticoResumo, StatusDiagnostico
from app.schemas.rotulo_dataset import (
    ElegibilidadeDataset,
    FonteRotulo,
    MotivoInelegivel,
    RotuloDatasetAutor,
    RotuloDatasetInfo,
    RotuloDatasetItem,
)
from app.schemas.usuario import TipoUsuario
from app.services import consentimento_service


class RotuloDatasetError(Exception):
    status_code = 409
    detail = "diagnóstico não pode ser rotulado neste estado"


class RotuloDatasetNaoEncontradoError(RotuloDatasetError):
    status_code = 404
    detail = "diagnóstico não encontrado"


class RotuloDatasetConflitoError(RotuloDatasetError):
    detail = "a versão do rótulo está desatualizada ou o diagnóstico não pode ser rotulado"


class ClassificacaoDatasetNaoEncontradaError(RotuloDatasetError):
    status_code = 422
    detail = "classificação inválida"


@dataclass(frozen=True)
class RotuloDatasetDetalhado:
    rotulo: RotuloDataset
    classificacao: ClassificacaoDiagnostico
    autor: User


async def _historico(db: AsyncSession, diagnostico_id: int) -> list[RotuloDatasetDetalhado]:
    result = await db.execute(
        select(RotuloDataset, ClassificacaoDiagnostico, User)
        .join(
            ClassificacaoDiagnostico,
            ClassificacaoDiagnostico.id == RotuloDataset.classificacao_id,
        )
        .join(User, User.id == RotuloDataset.admin_id)
        .where(RotuloDataset.diagnostico_id == diagnostico_id)
        .order_by(RotuloDataset.version.asc())
    )
    return [
        RotuloDatasetDetalhado(rotulo=rotulo, classificacao=classificacao, autor=autor)
        for rotulo, classificacao, autor in result.all()
    ]


def _para_item(item: RotuloDatasetDetalhado) -> RotuloDatasetItem:
    return RotuloDatasetItem(
        id=item.rotulo.id,
        diagnostico_id=item.rotulo.diagnostico_id,
        version=item.rotulo.version,
        classificacao=ClassificacaoDiagnosticoResumo(
            codigo=item.classificacao.codigo,
            nome_exibicao=item.classificacao.nome_exibicao,
            ordem=item.classificacao.ordem,
        ),
        autor=RotuloDatasetAutor(nome=item.autor.name),
        criado_em=item.rotulo.criado_em,
    )


async def criar(
    db: AsyncSession,
    diagnostico_id: int,
    classificacao_codigo: str,
    version_esperada: int,
    admin: User,
) -> RotuloDatasetItem:
    diagnostico = await db.scalar(
        select(Diagnostico).where(Diagnostico.id == diagnostico_id).with_for_update()
    )
    if diagnostico is None:
        raise RotuloDatasetNaoEncontradoError

    classificacao = await db.scalar(
        select(ClassificacaoDiagnostico).where(
            ClassificacaoDiagnostico.codigo == classificacao_codigo
        )
    )
    if classificacao is None:
        raise ClassificacaoDatasetNaoEncontradaError

    tem_imagem = await db.scalar(
        select(func.count()).select_from(Imagem).where(Imagem.diagnostico_id == diagnostico_id)
    )
    if (
        diagnostico.status != StatusDiagnostico.CONCLUIDO.value
        or diagnostico.classificacao_id is None
        or not tem_imagem
    ):
        raise RotuloDatasetConflitoError

    ultimo = await db.scalar(
        select(RotuloDataset)
        .where(RotuloDataset.diagnostico_id == diagnostico_id)
        .order_by(RotuloDataset.version.desc())
        .limit(1)
    )
    versao_atual = ultimo.version if ultimo else 0
    if version_esperada != versao_atual:
        raise RotuloDatasetConflitoError

    rotulo = RotuloDataset(
        diagnostico_id=diagnostico_id,
        admin_id=admin.id,
        classificacao_id=classificacao.id,
        version=versao_atual + 1,
        rotulo_anterior_id=ultimo.id if ultimo else None,
    )
    try:
        db.add(rotulo)
        await db.flush()
        await auditoria_queries.registrar_mutacao(
            db,
            admin,
            "diagnostico.rotulo_dataset.criar",
            "diagnostico",
            diagnostico_id,
            metadata={"version": rotulo.version, "classificacao": classificacao.codigo},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise RotuloDatasetConflitoError from exc
    except Exception:
        await db.rollback()
        raise
    return _para_item(RotuloDatasetDetalhado(rotulo, classificacao, admin))


async def obter_info(
    db: AsyncSession,
    diagnostico: Diagnostico,
    tem_revisao_profissional: bool,
    fonte_revisao: Literal["hality", "profissional"] = "profissional",
) -> RotuloDatasetInfo:
    historico = await _historico(db, diagnostico.id)
    itens = [_para_item(item) for item in historico]
    atual = itens[-1] if itens else None
    tem_rotulo_humano = atual is not None or tem_revisao_profissional
    fonte = "hality" if atual is not None else (fonte_revisao if tem_revisao_profissional else "ia")
    consentido = await consentimento_service.finalidade_vigente(
        db, diagnostico.paciente_id, Finalidade.IMAGE_TRAINING
    )
    if not tem_rotulo_humano:
        exportavel = False
        motivo = "sem_rotulo_humano"
    elif not consentido:
        exportavel = False
        motivo = "sem_consentimento"
    else:
        exportavel = True
        motivo = None

    return RotuloDatasetInfo(
        atual=atual,
        historico=list(reversed(itens[:-1])) if itens else [],
        fonte_efetiva=fonte,
        exportavel=exportavel,
        motivo=motivo,
    )


async def elegibilidade_em_lote(
    db: AsyncSession,
    diagnosticos: list[Diagnostico],
    qtd_imagens: dict[int, int],
    autores_das_revisoes: dict[int, uuid.UUID],
) -> dict[int, ElegibilidadeDataset]:
    """Elegibilidade de vários diagnósticos com as regras de `dataset_export_service`.

    Concluído, com imagem, com rótulo humano (Hality ou a última revisão) e com o
    consentimento de treino vigente. A exportação revalida tudo na hora de gerar o
    ZIP; aqui é só para a fila mostrar o estado sem buscar o detalhe de cada item.
    """
    if not diagnosticos:
        return {}
    ids = [d.id for d in diagnosticos]
    com_rotulo_hality = set(
        await db.scalars(
            select(RotuloDataset.diagnostico_id)
            .where(RotuloDataset.diagnostico_id.in_(ids))
            .distinct()
        )
    )
    autores = set(autores_das_revisoes.values())
    admins = (
        {
            usuario.id
            for usuario in await db.scalars(select(User).where(User.id.in_(autores)))
            if tem_papel(usuario, TipoUsuario.ADMIN)
        }
        if autores
        else set()
    )
    consentidos = await consentimento_service.titulares_com_finalidade_vigente(
        db, {d.paciente_id for d in diagnosticos}, Finalidade.IMAGE_TRAINING
    )

    resultado: dict[int, ElegibilidadeDataset] = {}
    for diagnostico in diagnosticos:
        autor = autores_das_revisoes.get(diagnostico.id)
        fonte: FonteRotulo
        if diagnostico.id in com_rotulo_hality:
            fonte = "hality"
        elif autor is not None:
            fonte = "hality" if autor in admins else "profissional"
        else:
            fonte = "ia"

        motivo: MotivoInelegivel | None = None
        if diagnostico.status != StatusDiagnostico.CONCLUIDO.value:
            motivo = "nao_concluido"
        elif qtd_imagens.get(diagnostico.id, 0) == 0:
            motivo = "sem_imagem"
        elif fonte == "ia":
            motivo = "sem_rotulo_humano"
        elif diagnostico.paciente_id not in consentidos:
            motivo = "sem_consentimento"
        resultado[diagnostico.id] = ElegibilidadeDataset(
            exportavel=motivo is None, fonte_efetiva=fonte, motivo=motivo
        )
    return resultado
