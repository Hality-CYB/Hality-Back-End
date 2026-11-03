import csv
import hashlib
import io
import re
import tempfile
import zipfile
from dataclasses import dataclass
from uuid import uuid4

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
    detail = "a seleção não está mais elegível para exportação"


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
    extension: str
    sha256: str


async def _candidate(db: AsyncSession, diagnostico: Diagnostico) -> _Candidate:
    if diagnostico.status != StatusDiagnostico.CONCLUIDO.value:
        raise DatasetExportError

    images = tuple(
        await db.scalars(
            select(Imagem).where(Imagem.diagnostico_id == diagnostico.id).order_by(Imagem.ordem)
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
        label_source = "profissional"
        label_version = revisao.versao

    if label is None or not await consentimento_service.finalidade_vigente(
        db, diagnostico.paciente_id, Finalidade.IMAGE_TRAINING
    ):
        raise DatasetExportError

    return _Candidate(
        diagnostico_id=diagnostico.id,
        images=images,
        label=label,
        label_source=label_source,
        label_version=label_version,
        consent_version=termo_vigente(Finalidade.IMAGE_TRAINING).versao,
    )


async def _candidates(db: AsyncSession, ids: list[int]) -> list[_Candidate]:
    diagnosticos = list(await db.scalars(select(Diagnostico).where(Diagnostico.id.in_(ids))))
    por_id = {diagnostico.id: diagnostico for diagnostico in diagnosticos}
    if len(por_id) != len(ids):
        raise DatasetExportNotFoundError
    return [await _candidate(db, por_id[diagnostico_id]) for diagnostico_id in ids]


def _sem_exif(conteudo: bytes, content_type: str) -> bytes:
    formato = _IMAGE_FORMATS.get(content_type)
    if formato is None:
        raise DatasetExportStorageError
    try:
        with Image.open(io.BytesIO(conteudo)) as imagem:
            imagem.load()
            saida = io.BytesIO()
            ImageOps.exif_transpose(imagem).save(saida, format=formato[1], exif=b"")
            return saida.getvalue()
    except Exception as exc:
        raise DatasetExportStorageError from exc


def _label_code(label: ClassificacaoDiagnostico) -> str:
    if not _SAFE_LABEL_CODE.fullmatch(label.codigo):
        raise DatasetExportStorageError
    return label.codigo


async def _artifacts(candidates: list[_Candidate]) -> list[_Artifact]:
    artifacts: list[_Artifact] = []
    for candidate in candidates:
        for image in candidate.images:
            try:
                original = await diagnostico_storage.ler_privado(image.url_arquivo)
                image_bytes = _sem_exif(original, image.content_type or "")
            except DatasetExportStorageError:
                raise
            except (OSError, ValueError) as exc:
                raise DatasetExportStorageError from exc
            extension = _IMAGE_FORMATS[image.content_type or ""][0]
            artifacts.append(
                _Artifact(
                    candidate=candidate,
                    image=image,
                    sample_id=uuid4().hex,
                    extension=extension,
                    sha256=hashlib.sha256(image_bytes).hexdigest(),
                )
            )
    return artifacts


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
        [(image.url_arquivo, image.sha256) for image in candidate.images],
    )


def _verificar_limite(spool: tempfile.SpooledTemporaryFile[bytes], settings: Settings) -> None:
    if spool.tell() > settings.dataset_export_max_bytes:
        raise DatasetExportLimitError


async def gerar(
    db: AsyncSession,
    admin: User,
    ids: list[int],
    settings: Settings,
    correlation_id: str,
) -> tempfile.SpooledTemporaryFile[bytes]:
    spool = None
    try:
        if len(ids) > settings.dataset_export_max_items:
            raise DatasetExportLimitError
        candidates = await _candidates(db, ids)
        artifacts = await _artifacts(candidates)
        spool = tempfile.SpooledTemporaryFile(  # noqa: SIM115 - response owns cleanup
            max_size=8 * 1024 * 1024, mode="w+b"
        )
        with zipfile.ZipFile(spool, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.csv", _manifest(artifacts))
            _verificar_limite(spool, settings)
            archive.writestr("README.md", _readme())
            _verificar_limite(spool, settings)
            for artifact in artifacts:
                path = (
                    f"images/{_label_code(artifact.candidate.label)}/"
                    f"{artifact.sample_id}.{artifact.extension}"
                )
                image_bytes = _sem_exif(
                    await diagnostico_storage.ler_privado(artifact.image.url_arquivo),
                    artifact.image.content_type or "",
                )
                if hashlib.sha256(image_bytes).hexdigest() != artifact.sha256:
                    raise DatasetExportError
                archive.writestr(path, image_bytes)
                _verificar_limite(spool, settings)
        confirmados = await _candidates(db, ids)
        if [_fingerprint(item) for item in candidates] != [
            _fingerprint(item) for item in confirmados
        ]:
            raise DatasetExportError
        _verificar_limite(spool, settings)
        spool.seek(0)
        await auditoria_queries.registrar_acesso(
            db,
            actor=admin,
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
        await db.commit()
        return spool
    except DatasetExportError as exc:
        await db.rollback()
        if spool is not None:
            spool.close()
        await _auditar_falha(db, admin, correlation_id, len(ids), exc.detail)
        raise
    except Exception as exc:
        await db.rollback()
        if spool is not None:
            spool.close()
        await _auditar_falha(db, admin, correlation_id, len(ids), "falha_interna")
        raise DatasetExportStorageError from exc


async def _auditar_falha(
    db: AsyncSession, admin: User, correlation_id: str, selected: int, reason: str
) -> None:
    await auditoria_queries.registrar_acesso(
        db,
        actor=admin,
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
