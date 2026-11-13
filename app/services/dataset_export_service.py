import asyncio
import csv
import hashlib
import io
import re
import tempfile
import zipfile
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.consentimentos import Finalidade, termo_vigente
from app.db import auditoria_queries
from app.models.classificacao_diagnostico import ClassificacaoDiagnostico
from app.models.diagnostico import Diagnostico
from app.models.diagnostico_revisao import DiagnosticoRevisao
from app.models.imagem import Imagem
from app.models.rotulo_dataset import RotuloDataset
from app.models.user import User
from app.schemas.diagnostico import StatusDiagnostico
from app.services import consentimento_service, diagnostico_storage

TAXONOMY_VERSION = "v1"
_IMAGE_FORMATS = {
    "image/jpeg": ("jpg", "JPEG"),
    "image/png": ("png", "PNG"),
    "image/webp": ("webp", "WEBP"),
}
# Reencodar é o que tira os metadados; os padrões do Pillow perdem qualidade
# (JPEG 75, WebP com perda), o que degrada o dado de treino.
_SAVE_OPTIONS = {
    "JPEG": {"quality": 95, "subsampling": 0},
    "PNG": {},
    "WEBP": {"lossless": True},
}
_MANIFEST_FIELDS = (
    "sample_id",
    "image_path",
    "label_code",
    "label_name",
    "label_source",
    "label_version",
    "taxonomy_version",
    "sha256",
)
_SAFE_LABEL_CODE = re.compile(r"^[A-Za-z0-9_-]+$")


class DatasetExportError(Exception):
    status_code = 409
    detail: str | dict = "a seleção não está mais elegível para exportação"


class DatasetExportDisabledError(DatasetExportError):
    detail = "exportação de dataset indisponível"


class DatasetExportIneligibleError(DatasetExportError):
    """Diz quais diagnósticos da seleção não podem ser exportados."""

    def __init__(self, diagnostico_ids: list[int]):
        super().__init__()
        self.detail = {
            "mensagem": "há diagnósticos não elegíveis na seleção",
            "diagnostico_ids": diagnostico_ids,
        }


class DatasetExportNotFoundError(DatasetExportError):
    status_code = 404
    detail = "seleção contém diagnóstico inexistente"


class DatasetExportLimitError(DatasetExportError):
    status_code = 413
    detail = "limite de exportação excedido"


class DatasetExportStorageError(DatasetExportError):
    status_code = 500
    detail = "não foi possível ler uma imagem para exportação"


@dataclass(frozen=True)
class _Candidate:
    diagnostico_id: int
    paciente_id: UUID
    images: tuple[Imagem, ...]
    label: ClassificacaoDiagnostico
    label_source: str
    label_version: int
    consent_version: str


@dataclass(frozen=True)
class _Artifact:
    candidate: _Candidate
    image: Imagem
    sample_id: str
    content_type: str
    extension: str
    original_sha256: str
    sha256: str


async def _candidate(db: AsyncSession, diagnostico: Diagnostico) -> _Candidate:
    if diagnostico.status != StatusDiagnostico.CONCLUIDO.value:
        raise DatasetExportError

    images = tuple(
        await db.scalars(
            select(Imagem)
            .where(Imagem.diagnostico_id == diagnostico.id)
            .order_by(Imagem.ordem, Imagem.id)
            .execution_options(populate_existing=True)
        )
    )
    if not images:
        raise DatasetExportError

    rotulo = await db.scalar(
        select(RotuloDataset)
        .where(RotuloDataset.diagnostico_id == diagnostico.id)
        .order_by(RotuloDataset.version.desc(), RotuloDataset.id.desc())
        .limit(1)
    )
    if rotulo is not None:
        label = await db.get(ClassificacaoDiagnostico, rotulo.classificacao_id)
        label_source = "hality"
        label_version = rotulo.version
    else:
        revisao = await db.scalar(
            select(DiagnosticoRevisao)
            .where(DiagnosticoRevisao.diagnostico_id == diagnostico.id)
            .order_by(DiagnosticoRevisao.versao.desc(), DiagnosticoRevisao.id.desc())
            .limit(1)
        )
        if revisao is None:
            raise DatasetExportError
        label = await db.get(ClassificacaoDiagnostico, revisao.classificacao_id)
        autor = await db.get(User, revisao.profissional_id)
        label_source = "hality" if autor and autor.role == "admin" else "profissional"
        label_version = revisao.versao

    if label is None or not await consentimento_service.finalidade_vigente(
        db, diagnostico.paciente_id, Finalidade.IMAGE_TRAINING
    ):
        raise DatasetExportError

    return _Candidate(
        diagnostico_id=diagnostico.id,
        paciente_id=diagnostico.paciente_id,
        images=images,
        label=label,
        label_source=label_source,
        label_version=label_version,
        consent_version=termo_vigente(Finalidade.IMAGE_TRAINING).versao,
    )


async def _candidates(db: AsyncSession, ids: list[int]) -> list[_Candidate]:
    diagnosticos = list(
        await db.scalars(
            select(Diagnostico)
            .where(Diagnostico.id.in_(ids))
            .execution_options(populate_existing=True)
        )
    )
    por_id = {diagnostico.id: diagnostico for diagnostico in diagnosticos}
    if len(por_id) != len(ids):
        raise DatasetExportNotFoundError
    candidatos: list[_Candidate] = []
    inelegiveis: list[int] = []
    for diagnostico_id in ids:
        try:
            candidatos.append(await _candidate(db, por_id[diagnostico_id]))
        except DatasetExportError:
            inelegiveis.append(diagnostico_id)
    if inelegiveis:
        raise DatasetExportIneligibleError(inelegiveis)
    return candidatos


def _content_type(image: Imagem, conteudo: bytes) -> str:
    """Usa o tipo gravado; imagens anteriores a 20/10 não têm, e o tipo sai do cabeçalho."""
    if image.content_type in _IMAGE_FORMATS:
        return image.content_type
    if conteudo.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if conteudo.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if conteudo[:4] == b"RIFF" and conteudo[8:12] == b"WEBP":
        return "image/webp"
    raise DatasetExportStorageError


def _sem_exif(conteudo: bytes, content_type: str) -> bytes:
    formato = _IMAGE_FORMATS.get(content_type)
    if formato is None:
        raise DatasetExportStorageError
    try:
        with Image.open(io.BytesIO(conteudo)) as imagem:
            imagem.load()
            saida = io.BytesIO()
            derivada = ImageOps.exif_transpose(imagem)
            derivada.info.clear()
            derivada.save(saida, format=formato[1], exif=b"", **_SAVE_OPTIONS[formato[1]])
            return saida.getvalue()
    except Exception as exc:
        raise DatasetExportStorageError from exc


def _label_code(label: ClassificacaoDiagnostico) -> str:
    if not _SAFE_LABEL_CODE.fullmatch(label.codigo):
        raise DatasetExportStorageError
    return label.codigo


async def _em_thread(func, /, *args):
    """Executa trabalho bloqueante sem abandonar a thread ao cancelar.

    ``asyncio.to_thread`` não interrompe a função subjacente. Esperar a task
    terminar antes de propagar o cancelamento evita fechar o ZIP/spool enquanto
    uma thread ainda escreve neles.
    """
    task = asyncio.create_task(asyncio.to_thread(func, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def _derivar_imagem(
    candidate: _Candidate, image: Imagem, original: bytes
) -> tuple[_Artifact, bytes]:
    """Valida e recodifica uma imagem fora do event loop."""
    original_sha256 = hashlib.sha256(original).hexdigest()
    if image.sha256 is not None and original_sha256 != image.sha256:
        raise DatasetExportStorageError
    content_type = _content_type(image, original)
    image_bytes = _sem_exif(original, content_type)
    return (
        _Artifact(
            candidate=candidate,
            image=image,
            sample_id=uuid4().hex,
            content_type=content_type,
            extension=_IMAGE_FORMATS[content_type][0],
            original_sha256=original_sha256,
            sha256=hashlib.sha256(image_bytes).hexdigest(),
        ),
        image_bytes,
    )


async def _artifact(candidate: _Candidate, image: Imagem) -> tuple[_Artifact, bytes]:
    try:
        original = await diagnostico_storage.ler_privado(image.url_arquivo)
        return await _em_thread(_derivar_imagem, candidate, image, original)
    except DatasetExportStorageError:
        raise
    except (OSError, ValueError) as exc:
        raise DatasetExportStorageError from exc


async def _storage_inalterado(artifacts: list[_Artifact]) -> None:
    """Confirma os bytes originais sem repetir a recodificação cara."""
    for artifact in artifacts:
        try:
            original = await diagnostico_storage.ler_privado(artifact.image.url_arquivo)
            atual = await _em_thread(hashlib.sha256, original)
        except (OSError, ValueError) as exc:
            raise DatasetExportStorageError from exc
        if atual.hexdigest() != artifact.original_sha256:
            raise DatasetExportError


def _manifest(artifacts: list[_Artifact]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_MANIFEST_FIELDS, lineterminator="\r\n")
    writer.writeheader()
    for artifact in artifacts:
        candidate = artifact.candidate
        writer.writerow(
            {
                "sample_id": artifact.sample_id,
                "image_path": (
                    f"images/{_label_code(candidate.label)}/{artifact.sample_id}.{artifact.extension}"
                ),
                "label_code": candidate.label.codigo,
                "label_name": candidate.label.nome_exibicao,
                "label_source": candidate.label_source,
                "label_version": candidate.label_version,
                "taxonomy_version": TAXONOMY_VERSION,
                "sha256": artifact.sha256,
            }
        )
    return output.getvalue().encode("utf-8")


def _readme() -> bytes:
    return (
        "Pacote de imagens consentidas para treinamento e avaliação.\n\n"
        "As imagens foram separadas de identificadores diretos, anamnese e observações, "
        "mas podem continuar identificáveis. Este arquivo não contém dados pessoais nem "
        "rótulos de IA usados como alvo.\n"
    ).encode()


def _fingerprint(candidate: _Candidate) -> tuple:
    return (
        candidate.label_source,
        candidate.label_version,
        candidate.label.codigo,
        tuple((image.url_arquivo, image.sha256) for image in candidate.images),
    )


def _verificar_limite(spool: tempfile.SpooledTemporaryFile[bytes], settings: Settings) -> None:
    if spool.tell() > settings.dataset_export_max_bytes:
        raise DatasetExportLimitError


async def _gravar_zip(archive: zipfile.ZipFile, path: str, content: bytes) -> None:
    """Compactação é CPU-bound e não pode bloquear o event loop da API."""
    await _em_thread(archive.writestr, path, content)


async def _bloquear_estado_exportado(db: AsyncSession, candidates: list[_Candidate]) -> None:
    """Impede revogação/revisão entre a revalidação final e o commit da exportação.

    Os escritores tomam locks exclusivos nessas mesmas linhas. Em SQLite,
    ``FOR SHARE`` é ignorado, mas produção usa PostgreSQL.
    """
    paciente_ids = sorted({candidate.paciente_id for candidate in candidates}, key=str)
    diagnostico_ids = sorted(candidate.diagnostico_id for candidate in candidates)
    await db.execute(
        select(User.id)
        .where(User.id.in_(paciente_ids))
        .order_by(User.id)
        .with_for_update(read=True)
    )
    await db.execute(
        select(Diagnostico.id)
        .where(Diagnostico.id.in_(diagnostico_ids))
        .order_by(Diagnostico.id)
        .with_for_update(read=True)
    )


async def gerar(
    db: AsyncSession,
    admin: User,
    ids: list[int],
    settings: Settings,
    correlation_id: str,
) -> tempfile.SpooledTemporaryFile[bytes]:
    spool = None
    ator = auditoria_queries.copia_do_ator(admin)
    try:
        if not settings.dataset_export_enabled:
            raise DatasetExportDisabledError
        if len(ids) > settings.dataset_export_max_items:
            raise DatasetExportLimitError
        candidates = await _candidates(db, ids)
        fingerprints = [_fingerprint(item) for item in candidates]
        artifacts: list[_Artifact] = []
        spool = tempfile.SpooledTemporaryFile(  # noqa: SIM115 - response owns cleanup
            max_size=8 * 1024 * 1024, mode="w+b"
        )
        archive = zipfile.ZipFile(spool, "w", compression=zipfile.ZIP_DEFLATED)
        try:
            for candidate in candidates:
                for image in candidate.images:
                    artifact, image_bytes = await _artifact(candidate, image)
                    artifacts.append(artifact)
                    path = (
                        f"images/{_label_code(candidate.label)}/"
                        f"{artifact.sample_id}.{artifact.extension}"
                    )
                    await _gravar_zip(archive, path, image_bytes)
                    _verificar_limite(spool, settings)
            await _gravar_zip(archive, "manifest.csv", _manifest(artifacts))
            _verificar_limite(spool, settings)
            await _gravar_zip(archive, "README.md", _readme())
            _verificar_limite(spool, settings)
        finally:
            await _em_thread(archive.close)
        await _storage_inalterado(artifacts)
        await _bloquear_estado_exportado(db, candidates)
        confirmados = await _candidates(db, ids)
        if fingerprints != [_fingerprint(item) for item in confirmados]:
            raise DatasetExportError
        _verificar_limite(spool, settings)
        spool.seek(0)
        await auditoria_queries.registrar_acesso(
            db,
            actor=ator,
            action="dataset.exportar",
            resource="dataset_export",
            resource_id="lote",
            metadata={
                "correlation_id": correlation_id,
                "contagem_selecionada": len(ids),
                "contagem_exportada": len(artifacts),
                "taxonomy_version": TAXONOMY_VERSION,
                "resultado": "sucesso",
            },
        )
        # O pacote está pronto e revalidado. Confirma aqui, e não no fim do
        # streaming: os locks não podem depender da velocidade do cliente, senão
        # um download parado trava a revogação de consentimento do paciente. A
        # auditoria de sucesso registra a liberação do pacote, não o recebimento.
        await db.commit()
        return spool
    except asyncio.CancelledError:
        if spool is not None:
            spool.close()
        await db.rollback()
        raise
    except DatasetExportError as exc:
        await db.rollback()
        if spool is not None:
            spool.close()
        # A auditoria guarda só o motivo e contagens: os ids da seleção vão na
        # resposta ao admin, nunca na trilha.
        motivo = exc.detail if isinstance(exc.detail, str) else exc.detail["mensagem"]
        await _auditar_falha(db, ator, correlation_id, len(ids), motivo)
        raise
    except Exception as exc:
        await db.rollback()
        if spool is not None:
            spool.close()
        await _auditar_falha(db, ator, correlation_id, len(ids), "falha_interna")
        raise DatasetExportStorageError from exc


async def _auditar_falha(
    db: AsyncSession, ator: SimpleNamespace, correlation_id: str, selected: int, reason: str
) -> None:
    await auditoria_queries.registrar_acesso(
        db,
        actor=ator,
        action="dataset.exportar",
        resource="dataset_export",
        resource_id="lote",
        result="falha",
        metadata={
            "correlation_id": correlation_id,
            "contagem_selecionada": selected,
            "contagem_exportada": 0,
            "resultado": reason,
        },
    )
    await db.commit()
