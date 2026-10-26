import csv
import hashlib
import io
import tempfile
import uuid
import zipfile
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import diagnostico_queries
from app.models.classificacao_diagnostico import ClassificacaoDiagnostico
from app.models.diagnostico import Diagnostico
from app.models.imagem import Imagem
from app.services import consentimento_service, diagnostico_storage
from app.services.consentimento_service import Finalidade

TAXONOMY_VERSION = "v1"
SUPPORTED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


class DatasetExportError(Exception):
    status_code = 409
    public_detail = "a seleção não está mais elegível para exportação"


class DatasetExportSelectionError(DatasetExportError):
    status_code = 400
    public_detail = "seleção inválida"


class DatasetExportNotFoundError(DatasetExportError):
    status_code = 404
    public_detail = "um item da seleção não foi encontrado"


class DatasetExportLimitError(DatasetExportError):
    status_code = 413
    public_detail = "limite de exportação excedido"


class DatasetExportStorageError(DatasetExportError):
    status_code = 500
    public_detail = "não foi possível preparar a exportação"


@dataclass
class DatasetExportResult:
    arquivo: tempfile.SpooledTemporaryFile[bytes]
    registros: int
    imagens: int
    bytes_imagem: int


@dataclass(frozen=True)
class _ExportItem:
    diagnostico: Diagnostico
    imagem: Imagem
    label: ClassificacaoDiagnostico
    label_source: str
    label_version: str
    sample_id: str


def _extension(imagem: Imagem, conteudo: bytes) -> str:
    if imagem.content_type in SUPPORTED_TYPES:
        return SUPPORTED_TYPES[imagem.content_type]
    if conteudo.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if conteudo.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if conteudo.startswith(b"RIFF") and conteudo[8:12] == b"WEBP":
        return ".webp"
    raise DatasetExportStorageError


def _sem_metadados(conteudo: bytes, extension: str) -> bytes:
    if extension == ".jpg" and conteudo.startswith(b"\xff\xd8\xff"):
        saida = bytearray(conteudo[:2])
        posicao = 2
        while posicao + 4 <= len(conteudo) and conteudo[posicao] == 0xFF:
            marcador = conteudo[posicao + 1]
            if marcador in {0xD8, 0xD9}:
                break
            tamanho = int.from_bytes(conteudo[posicao + 2 : posicao + 4], "big")
            fim = posicao + 2 + tamanho
            if fim > len(conteudo):
                return conteudo
            if marcador != 0xE1 or conteudo[posicao + 4 : posicao + 10] != b"Exif\x00\x00":
                saida.extend(conteudo[posicao:fim])
            posicao = fim
            if marcador == 0xDA:
                saida.extend(conteudo[posicao:])
                break
        return bytes(saida)
    if extension == ".png" and conteudo.startswith(b"\x89PNG\r\n\x1a\n"):
        saida = bytearray(conteudo[:8])
        posicao = 8
        while posicao + 12 <= len(conteudo):
            tamanho = int.from_bytes(conteudo[posicao : posicao + 4], "big")
            fim = posicao + 12 + tamanho
            if fim > len(conteudo):
                return conteudo
            tipo = conteudo[posicao + 4 : posicao + 8]
            if tipo not in {b"eXIf", b"tEXt", b"zTXt", b"iTXt"}:
                saida.extend(conteudo[posicao:fim])
            posicao = fim
            if tipo == b"IEND":
                break
        return bytes(saida)
    if extension == ".webp" and conteudo.startswith(b"RIFF"):
        saida = bytearray(conteudo[:12])
        posicao = 12
        while posicao + 8 <= len(conteudo):
            tipo = conteudo[posicao : posicao + 4]
            tamanho = int.from_bytes(conteudo[posicao + 4 : posicao + 8], "little")
            fim = posicao + 8 + tamanho + (tamanho & 1)
            if fim > len(conteudo):
                return conteudo
            if tipo != b"EXIF":
                saida.extend(conteudo[posicao:fim])
            posicao = fim
        saida[4:8] = (len(saida) - 8).to_bytes(4, "little")
        return bytes(saida)
    return conteudo


def _csv_bytes(items: list[_ExportItem]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(
        [
            "sample_id",
            "image_path",
            "label_code",
            "label_name",
            "label_source",
            "label_version",
            "taxonomy_version",
            "sha256",
        ]
    )
    for item in items:
        extension = SUPPORTED_TYPES.get(item.imagem.content_type or "", ".bin")
        writer.writerow(
            [
                item.sample_id,
                f"images/{item.label.codigo}/{item.sample_id}{extension}",
                item.label.codigo,
                item.label.nome_exibicao,
                item.label_source,
                item.label_version,
                TAXONOMY_VERSION,
                item.imagem.sha256 or "",
            ]
        )
    return output.getvalue().encode("utf-8")


def _readme() -> bytes:
    return (
        b"Hality dataset export\n\n"
        b"This package contains consented images and effective human labels.\n"
        b"It is pseudonymous, not anonymous: image pixels may still identify a person.\n"
        b"The package excludes patient identifiers, anamnesis, observations and AI-only labels.\n"
    )


async def _eligible_items(db: AsyncSession, diagnostico_ids: list[int]) -> list[_ExportItem]:
    result = await db.execute(
        select(Diagnostico).where(Diagnostico.id.in_(diagnostico_ids)).order_by(Diagnostico.id)
    )
    diagnosticos = result.scalars().all()
    if {diagnostico.id for diagnostico in diagnosticos} != set(diagnostico_ids):
        raise DatasetExportNotFoundError

    imagens_result = await db.execute(
        select(Imagem)
        .where(Imagem.diagnostico_id.in_(diagnostico_ids))
        .order_by(Imagem.diagnostico_id, Imagem.ordem)
    )
    imagens_por_diagnostico: dict[int, list[Imagem]] = {}
    for imagem in imagens_result.scalars().all():
        imagens_por_diagnostico.setdefault(imagem.diagnostico_id, []).append(imagem)
    revisoes = await diagnostico_queries.buscar_ultimas_revisoes(db, diagnostico_ids)
    items: list[_ExportItem] = []

    for diagnostico in diagnosticos:
        consentido = await consentimento_service.finalidade_vigente(
            db, diagnostico.paciente_id, Finalidade.IMAGE_TRAINING
        )
        imagens = imagens_por_diagnostico.get(diagnostico.id, [])
        if diagnostico.status != "concluido" or not consentido or not imagens:
            raise DatasetExportError

        revisao = revisoes.get(diagnostico.id)
        if revisao is not None:
            label = revisao.classificacao
            label_source = "hality"
            label_version = str(revisao.revisao.versao)
        elif diagnostico.profissional_revisor_id is not None and diagnostico.classificacao_id:
            label = await db.get(ClassificacaoDiagnostico, diagnostico.classificacao_id)
            if label is None:
                raise DatasetExportError
            label_source = "profissional"
            label_version = "snapshot"
        else:
            raise DatasetExportError

        items.extend(
            _ExportItem(
                diagnostico=diagnostico,
                imagem=imagem,
                label=label,
                label_source=label_source,
                label_version=label_version,
                sample_id=uuid.uuid4().hex,
            )
            for imagem in imagens
        )
    return items


async def _revalidate(db: AsyncSession, items: list[_ExportItem]) -> None:
    current = await _eligible_items(db, [item.diagnostico.id for item in items])
    if len(current) != len(items) or any(
        old.imagem.id != new.imagem.id
        or old.label.codigo != new.label.codigo
        or old.label_version != new.label_version
        for old, new in zip(items, current, strict=True)
    ):
        raise DatasetExportError


async def criar_exportacao(db: AsyncSession, diagnostico_ids: list[int]) -> DatasetExportResult:
    settings = get_settings()
    if not settings.dataset_export_enabled:
        raise DatasetExportError
    if len(diagnostico_ids) != len(set(diagnostico_ids)):
        raise DatasetExportSelectionError
    if len(diagnostico_ids) > settings.dataset_export_max_records:
        raise DatasetExportLimitError

    items = await _eligible_items(db, diagnostico_ids)
    total = sum(item.imagem.tamanho_bytes or 0 for item in items)
    if total > settings.dataset_export_max_bytes:
        raise DatasetExportLimitError

    arquivo = tempfile.SpooledTemporaryFile(  # noqa: SIM115 - fechado pelo endpoint após o stream
        max_size=8 * 1024 * 1024, mode="w+b"
    )
    bytes_lidos = 0
    try:
        with zipfile.ZipFile(arquivo, "w", compression=zipfile.ZIP_DEFLATED) as pacote:
            for item in items:
                try:
                    conteudo = await diagnostico_storage.ler(item.imagem.url_arquivo)
                except (FileNotFoundError, OSError) as exc:
                    raise DatasetExportStorageError from exc
                bytes_lidos += len(conteudo)
                if bytes_lidos > settings.dataset_export_max_bytes:
                    raise DatasetExportLimitError
                checksum = hashlib.sha256(conteudo).hexdigest()
                if item.imagem.sha256 and checksum != item.imagem.sha256:
                    raise DatasetExportStorageError
                extension = _extension(item.imagem, conteudo)
                derivado = _sem_metadados(conteudo, extension)
                pacote.writestr(f"images/{item.label.codigo}/{item.sample_id}{extension}", derivado)
                item.imagem.sha256 = hashlib.sha256(derivado).hexdigest()
            pacote.writestr("manifest.csv", _csv_bytes(items))
            pacote.writestr("README.md", _readme())
        await _revalidate(db, items)
        arquivo.seek(0)
        return DatasetExportResult(
            arquivo, len(items), len({i.diagnostico.id for i in items}), bytes_lidos
        )
    except Exception:
        arquivo.close()
        raise
