from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classificacao_diagnostico import (
    ClassificacaoDiagnostico,
)
from app.models.conteudo_diagnostico import (
    ConteudoDiagnostico,
)
from app.models.diagnostico import Diagnostico
from app.models.imagem import Imagem
from app.models.paciente_profissional import (
    PacienteProfissional,
)
from app.models.user import User


@dataclass
class DadosDetalheDiagnostico:
    imagens: list[Imagem]
    classificacao: ClassificacaoDiagnostico | None
    conteudos: list[ConteudoDiagnostico]
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


async def buscar_por_id(
    db: AsyncSession,
    diagnostico_id: int,
) -> Diagnostico | None:
    result = await db.execute(select(Diagnostico).where(Diagnostico.id == diagnostico_id))

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

    if ordem == "data_asc":
        ordenacao = (Diagnostico.data_diagnostico.asc(), Diagnostico.id.asc())
    else:
        ordenacao = (Diagnostico.data_diagnostico.desc(), Diagnostico.id.desc())

    result = await db.execute(
        select(Diagnostico, ClassificacaoDiagnostico)
        .outerjoin(
            ClassificacaoDiagnostico,
            Diagnostico.classificacao_id == ClassificacaoDiagnostico.id,
        )
        .where(*filtros)
        .order_by(*ordenacao)
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


async def buscar_por_anamnese(
    db: AsyncSession,
    anamnese_id: int,
) -> Diagnostico | None:
    result = await db.execute(select(Diagnostico).where(Diagnostico.anamnese_id == anamnese_id))

    return result.scalar_one_or_none()


async def inserir(
    db: AsyncSession,
    paciente_id: int,
    anamnese_id: int,
    url_arquivo: str,
    parametros_captura: dict,
) -> Diagnostico:
    diagnostico = Diagnostico(
        paciente_id=paciente_id,
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
) -> list[ConteudoDiagnostico]:
    result = await db.execute(
        select(ConteudoDiagnostico)
        .where(ConteudoDiagnostico.classificacao_id == classificacao_id)
        .order_by(ConteudoDiagnostico.id.asc())
    )

    return list(result.scalars().all())


async def tem_profissional_vinculado(
    db: AsyncSession,
    paciente_id: int,
) -> bool:
    result = await db.execute(
        select(PacienteProfissional.id)
        .where(PacienteProfissional.paciente_id == paciente_id)
        .limit(1)
    )

    return result.scalar_one_or_none() is not None


async def buscar_nome_usuario(
    db: AsyncSession,
    usuario_id: int,
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
    conteudos: list[ConteudoDiagnostico] = []

    if diagnostico.classificacao_id is not None:
        classificacao = await buscar_classificacao(
            db,
            diagnostico.classificacao_id,
        )

        conteudos = await listar_conteudos_por_classificacao(
            db,
            diagnostico.classificacao_id,
        )

    vinculado = await tem_profissional_vinculado(
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
