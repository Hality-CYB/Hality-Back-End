import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import paciente_profissional_queries
from app.models.classificacao_diagnostico import (
    ClassificacaoDiagnostico,
)
from app.models.conteudo import Conteudo, StatusConteudo
from app.models.diagnostico import Diagnostico
from app.models.imagem import Imagem
from app.models.user import User


@dataclass
class DadosDetalheDiagnostico:
    imagens: list[Imagem]
    classificacao: ClassificacaoDiagnostico | None
    conteudos: list[Conteudo]
    tem_profissional_vinculado: bool
    profissional_nome: str | None


@dataclass
class DiagnosticoListado:
    diagnostico: Diagnostico
    classificacao: ClassificacaoDiagnostico | None


@dataclass
class DiagnosticosPaginados:
    itens: list[DiagnosticoListado]
    total: int


def _ordenacao(ordem: str):
    if ordem == "data_asc":
        return (Diagnostico.data_diagnostico.asc(), Diagnostico.id.asc())

    # `id` como desempate garante paginação estável com datas iguais.
    return (Diagnostico.data_diagnostico.desc(), Diagnostico.id.desc())


async def buscar_por_id(
    db: AsyncSession,
    diagnostico_id: int,
) -> Diagnostico | None:
    result = await db.execute(select(Diagnostico).where(Diagnostico.id == diagnostico_id))

    return result.scalar_one_or_none()


async def buscar_paciente_por_arquivo_imagem(
    db: AsyncSession,
    nome_arquivo: str,
) -> uuid.UUID | None:
    result = await db.execute(
        select(Diagnostico.paciente_id)
        .join(Imagem, Imagem.diagnostico_id == Diagnostico.id)
        .where(Imagem.url_arquivo.endswith(f"/{nome_arquivo}", autoescape=True))
        .limit(1)
    )

    return result.scalar_one_or_none()


async def listar_por_paciente(
    db: AsyncSession,
    paciente_id: int,
    data_inicio: datetime | None,
    data_fim: datetime | None,
    status: str | None,
    pagina: int,
    limite: int,
    ordem: str,
) -> DiagnosticosPaginados:
    filtros = [Diagnostico.paciente_id == paciente_id]

    if data_inicio is not None:
        filtros.append(Diagnostico.data_diagnostico >= data_inicio)

    if data_fim is not None:
        filtros.append(Diagnostico.data_diagnostico <= data_fim)

    if status is not None:
        filtros.append(Diagnostico.status == status)

    total_result = await db.execute(select(func.count()).select_from(Diagnostico).where(*filtros))
    total = total_result.scalar_one()

    result = await db.execute(
        select(Diagnostico, ClassificacaoDiagnostico)
        .outerjoin(
            ClassificacaoDiagnostico,
            Diagnostico.classificacao_id == ClassificacaoDiagnostico.id,
        )
        .where(*filtros)
        .order_by(*_ordenacao(ordem))
        .offset((pagina - 1) * limite)
        .limit(limite)
    )

    return DiagnosticosPaginados(
        itens=[
            DiagnosticoListado(
                diagnostico=diagnostico,
                classificacao=classificacao,
            )
            for diagnostico, classificacao in result.all()
        ],
        total=total,
    )


async def listar_admin(
    db: AsyncSession,
    paciente_id: uuid.UUID | None,
    classificacao_codigo: str | None,
    sem_classificacao: bool,
    status: str | None,
    data_inicio: datetime | None,
    data_fim: datetime | None,
    pagina: int,
    limite: int,
    ordem: str,
) -> DiagnosticosPaginados:
    """Listagem administrativa (todos os pacientes) com filtros opcionais.

    Estende a mesma consulta/estrutura de `listar_por_paciente`: só muda o
    conjunto de filtros. Não carrega imagens nem anamnese.
    """
    filtros = []

    if paciente_id is not None:
        filtros.append(Diagnostico.paciente_id == paciente_id)

    if status is not None:
        filtros.append(Diagnostico.status == status)

    if data_inicio is not None:
        filtros.append(Diagnostico.data_diagnostico >= data_inicio)

    if data_fim is not None:
        filtros.append(Diagnostico.data_diagnostico <= data_fim)

    if sem_classificacao:
        filtros.append(Diagnostico.classificacao_id.is_(None))
    elif classificacao_codigo is not None:
        # Subquery no lugar de join: o COUNT usa os mesmos filtros sem precisar de join.
        filtros.append(
            Diagnostico.classificacao_id.in_(
                select(ClassificacaoDiagnostico.id).where(
                    ClassificacaoDiagnostico.codigo == classificacao_codigo
                )
            )
        )

    total_result = await db.execute(select(func.count()).select_from(Diagnostico).where(*filtros))
    total = total_result.scalar_one()

    result = await db.execute(
        select(Diagnostico, ClassificacaoDiagnostico)
        .outerjoin(
            ClassificacaoDiagnostico,
            Diagnostico.classificacao_id == ClassificacaoDiagnostico.id,
        )
        .where(*filtros)
        .order_by(*_ordenacao(ordem))
        .offset((pagina - 1) * limite)
        .limit(limite)
    )

    return DiagnosticosPaginados(
        itens=[
            DiagnosticoListado(diagnostico=diagnostico, classificacao=classificacao)
            for diagnostico, classificacao in result.all()
        ],
        total=total,
    )


async def contar_imagens(
    db: AsyncSession,
    diagnostico_id: int,
) -> int:
    result = await db.execute(
        select(func.count()).select_from(Imagem).where(Imagem.diagnostico_id == diagnostico_id)
    )

    return result.scalar_one()


async def buscar_por_anamnese(
    db: AsyncSession,
    anamnese_id: int,
) -> Diagnostico | None:
    result = await db.execute(select(Diagnostico).where(Diagnostico.anamnese_id == anamnese_id))

    return result.scalar_one_or_none()


async def inserir(
    db: AsyncSession,
    paciente_id: uuid.UUID,
    executor_id: uuid.UUID,
    anamnese_id: int,
    url_arquivo: str,
    parametros_captura: dict,
) -> Diagnostico:
    # Diagnóstico e imagem entram no mesmo commit: ou os dois existem, ou
    # nenhum (e o service remove o arquivo do storage).
    diagnostico = Diagnostico(
        paciente_id=paciente_id,
        executor_id=executor_id,
        anamnese_id=anamnese_id,
        classificacao_id=None,
        escala_saburra=None,
        confianca_ia=None,
        status="processando",
    )

    db.add(diagnostico)

    await db.flush()

    imagem = Imagem(
        diagnostico_id=diagnostico.id,
        url_arquivo=url_arquivo,
        ordem=1,
        parametros_captura=parametros_captura,
    )

    db.add(imagem)

    await db.commit()
    await db.refresh(diagnostico)

    return diagnostico


async def listar_imagens(
    db: AsyncSession,
    diagnostico_id: int,
) -> list[Imagem]:
    result = await db.execute(
        select(Imagem).where(Imagem.diagnostico_id == diagnostico_id).order_by(Imagem.ordem.asc())
    )

    return list(result.scalars().all())


async def buscar_classificacao(
    db: AsyncSession,
    classificacao_id: int,
) -> ClassificacaoDiagnostico | None:
    result = await db.execute(
        select(ClassificacaoDiagnostico).where(ClassificacaoDiagnostico.id == classificacao_id)
    )

    return result.scalar_one_or_none()


async def buscar_classificacao_por_ordem(
    db: AsyncSession,
    ordem: int,
) -> ClassificacaoDiagnostico | None:
    result = await db.execute(
        select(ClassificacaoDiagnostico).where(ClassificacaoDiagnostico.ordem == ordem)
    )

    return result.scalar_one_or_none()


async def listar_conteudos_por_classificacao(
    db: AsyncSession,
    classificacao_id: int,
) -> list[Conteudo]:
    result = await db.execute(
        select(Conteudo)
        .where(
            Conteudo.classificacao_ids.any(classificacao_id),
            Conteudo.status == StatusConteudo.PUBLICADO,
            Conteudo.criado_por_id.is_not(None),
        )
        .order_by(Conteudo.ordem.asc(), Conteudo.id.asc())
    )

    return list(result.scalars().all())


async def buscar_nome_usuario(
    db: AsyncSession,
    usuario_id: uuid.UUID,
) -> str | None:
    result = await db.execute(select(User.name).where(User.id == usuario_id))

    return result.scalar_one_or_none()


async def buscar_dados_detalhe(
    db: AsyncSession,
    diagnostico: Diagnostico,
) -> DadosDetalheDiagnostico:
    imagens = await listar_imagens(
        db,
        diagnostico.id,
    )

    classificacao = None
    conteudos: list[Conteudo] = []

    if diagnostico.classificacao_id is not None:
        classificacao = await buscar_classificacao(
            db,
            diagnostico.classificacao_id,
        )

        conteudos = await listar_conteudos_por_classificacao(
            db,
            diagnostico.classificacao_id,
        )

    vinculado = await paciente_profissional_queries.paciente_tem_vinculo_ativo(
        db,
        diagnostico.paciente_id,
    )

    profissional_nome = None

    if diagnostico.profissional_revisor_id is not None:
        profissional_nome = await buscar_nome_usuario(
            db,
            diagnostico.profissional_revisor_id,
        )

    return DadosDetalheDiagnostico(
        imagens=imagens,
        classificacao=classificacao,
        conteudos=conteudos,
        tem_profissional_vinculado=vinculado,
        profissional_nome=profissional_nome,
    )


async def concluir_mock(
    db: AsyncSession,
    diagnostico: Diagnostico,
    classificacao_id: int,
    escala_saburra: int,
    confianca_ia: float,
) -> Diagnostico:
    diagnostico.classificacao_id = classificacao_id

    diagnostico.escala_saburra = escala_saburra

    diagnostico.confianca_ia = confianca_ia

    diagnostico.status = "concluido"

    if hasattr(diagnostico, "erro"):
        diagnostico.erro = None

    await db.commit()
    await db.refresh(diagnostico)

    return diagnostico


async def marcar_falha(
    db: AsyncSession,
    diagnostico: Diagnostico,
    erro: str,
) -> Diagnostico:
    diagnostico.classificacao_id = None
    diagnostico.escala_saburra = None
    diagnostico.confianca_ia = None
    diagnostico.status = "falha"

    if hasattr(diagnostico, "erro"):
        diagnostico.erro = erro

    await db.commit()
    await db.refresh(diagnostico)

    return diagnostico
