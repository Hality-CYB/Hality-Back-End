import asyncio
import csv
import hashlib
import io
import re
import tempfile
import uuid
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

from PIL import Image as PillowImage
from PIL import ImageOps
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.policies import obter_correlation_id
from app.core.config import get_settings
from app.core.consentimentos import Finalidade
from app.db import auditoria_queries, diagnostico_queries
from app.models.diagnostico import Diagnostico
from app.models.imagem import Imagem
from app.services import consentimento_service, diagnostico_storage

TAXONOMY_VERSION = "classificacoes_diagnostico_v1"
_SAFE_CODE = re.compile(r"^[A-Za-z0-9_-]+$")
_FORMATS = {
    "image/jpeg": (".jpg", "JPEG"),
    "image/png": (".png", "PNG"),
    "image/webp": (".webp", "WEBP"),
}


class DatasetExportError(Exception):
    status_code = 409

    def __init__(self, detail: str, *, status_code: int | None = None):
        super().__init__(detail)
        if status_code is not None:
            self.status_code = status_code
        self.detail = detail


class DatasetExportArtifact:
    def __init__(self, file: BinaryIO, filename: str):
        self.file = file
        self.filename = filename

    async def chunks(self) -> AsyncIterator[bytes]:
        try:
            while True:
                chunk = await asyncio.to_thread(self.file.read, 1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(self.file.close)


def _read_private_image(imagem: Imagem) -> bytes:
    nome = Path(imagem.url_arquivo).name
    caminho = diagnostico_storage.resolver_caminho(nome)
    if caminho is None:
        raise DatasetExportError("arquivo de imagem indisponível", status_code=500)
    try:
        conteudo = caminho.read_bytes()
    except OSError as exc:
        raise DatasetExportError("falha ao ler arquivo de imagem", status_code=500) from exc
    if len(conteudo) > diagnostico_storage.MAX_IMAGE_BYTES:
        raise DatasetExportError("arquivo de imagem excede o limite", status_code=413)
    return conteudo


def _sanitizar_imagem(conteudo: bytes, content_type: str | None) -> bytes:
    formato = _FORMATS.get(content_type or "")
    if formato is None:
        raise DatasetExportError("tipo de imagem não suportado", status_code=500)
    try:
        with PillowImage.open(io.BytesIO(conteudo)) as original:
            pixels = ImageOps.exif_transpose(original)
            pixels.load()
            pixels = pixels.copy()
            saida = io.BytesIO()
            opcoes = {}
            if formato[1] == "JPEG":
                opcoes = {"quality": 95}
            elif formato[1] == "WEBP":
                opcoes = {"lossless": True}
            pixels.save(saida, format=formato[1], **opcoes)
            return saida.getvalue()
    except Exception as exc:
        raise DatasetExportError("arquivo de imagem corrompido", status_code=500) from exc


async def _auditar(db: AsyncSession, admin, resultado: str, metadata: dict) -> None:
    await auditoria_queries.registrar_acesso(
        db,
        actor=admin,
        action="dataset.exportar",
        resource="dataset_export",
        resource_id="lote",
        result=resultado,
        metadata={"correlation_id": obter_correlation_id(), **metadata},
    )
    await db.commit()


async def exportar(db: AsyncSession, admin, diagnostico_ids: list[int]) -> DatasetExportArtifact:
    settings = get_settings()
    metadata = {"solicitados": len(diagnostico_ids), "incluidos": 0, "excluidos": 0}
    if not settings.dataset_export_enabled:
        await _auditar(db, admin, "negado", {**metadata, "motivo": "desabilitado"})
        raise DatasetExportError("exportação de dataset indisponível", status_code=404)
    if len(diagnostico_ids) > settings.dataset_export_max_records:
        await _auditar(db, admin, "falha", {**metadata, "motivo": "limite_registros"})
        raise DatasetExportError("limite de registros excedido", status_code=413)

    result = await db.execute(select(Diagnostico).where(Diagnostico.id.in_(diagnostico_ids)))
    diagnosticos = {item.id: item for item in result.scalars().all()}
    if len(diagnosticos) != len(diagnostico_ids):
        await _auditar(db, admin, "falha", {**metadata, "motivo": "selecao_inexistente"})
        raise DatasetExportError("seleção contém diagnóstico inexistente", status_code=404)

    selecionados: list[tuple[Diagnostico, Imagem, object, str, int]] = []
    for diagnostico_id in diagnostico_ids:
        diagnostico = diagnosticos[diagnostico_id]
        revisao = await diagnostico_queries.buscar_ultima_revisao(db, diagnostico_id)
        if revisao is not None:
            classificacao = revisao.classificacao
            fonte, versao = "profissional", revisao.revisao.versao
        elif diagnostico.profissional_revisor_id and diagnostico.classificacao_id:
            classificacao = await diagnostico_queries.buscar_classificacao(
                db, diagnostico.classificacao_id
            )
            fonte, versao = "profissional", 0
        else:
            classificacao, fonte, versao = None, "ia", 0
        imagens = await diagnostico_queries.listar_imagens(db, diagnostico_id)
        consentido = await consentimento_service.finalidade_vigente(
            db, diagnostico.paciente_id, Finalidade.IMAGE_TRAINING
        )
        if (
            diagnostico.status != "concluido"
            or not imagens
            or not consentido
            or classificacao is None
        ):
            await _auditar(db, admin, "falha", {**metadata, "motivo": "item_inelegivel"})
            raise DatasetExportError("seleção deixou de ser elegível")
        for imagem in imagens:
            selecionados.append((diagnostico, imagem, classificacao, fonte, versao))

    if not selecionados:
        await _auditar(db, admin, "falha", {**metadata, "motivo": "sem_imagens"})
        raise DatasetExportError("nenhum item elegível")

    arquivo = tempfile.SpooledTemporaryFile(  # noqa: SIM115
        max_size=8 * 1024 * 1024, mode="w+b"
    )
    total_bytes = 0
    manifest = io.StringIO(newline="")
    writer = csv.DictWriter(
        manifest,
        fieldnames=[
            "sample_id",
            "image_path",
            "label_code",
            "label_name",
            "label_source",
            "label_version",
            "taxonomy_version",
            "checksum_sha256",
        ],
        lineterminator="\r\n",
    )
    writer.writeheader()
    try:
        with zipfile.ZipFile(arquivo, "w", zipfile.ZIP_DEFLATED) as pacote:
            for _, imagem, classificacao, fonte, versao in selecionados:
                derivada = await asyncio.to_thread(
                    _sanitizar_imagem,
                    await asyncio.to_thread(_read_private_image, imagem),
                    imagem.content_type,
                )
                total_bytes += len(derivada)
                if total_bytes > settings.dataset_export_max_bytes:
                    raise DatasetExportError("limite de bytes excedido", status_code=413)
                if not _SAFE_CODE.fullmatch(classificacao.codigo):
                    raise DatasetExportError("código de classificação inválido", status_code=500)
                sample_id = uuid.uuid4().hex
                image_path = (
                    f"images/{classificacao.codigo}/{sample_id}{_FORMATS[imagem.content_type][0]}"
                )
                pacote.writestr(image_path, derivada)
                writer.writerow(
                    {
                        "sample_id": sample_id,
                        "image_path": image_path,
                        "label_code": classificacao.codigo,
                        "label_name": classificacao.nome_exibicao,
                        "label_source": fonte,
                        "label_version": versao,
                        "taxonomy_version": TAXONOMY_VERSION,
                        "checksum_sha256": hashlib.sha256(derivada).hexdigest(),
                    }
                )
            pacote.writestr("manifest.csv", manifest.getvalue().encode("utf-8"))
            pacote.writestr(
                "README.md",
                "Pacote de imagens consentidas para treinamento.\n"
                "As imagens podem continuar identificáveis; este arquivo não é anônimo.\n",
            )
        arquivo.seek(0)
        metadata.update(incluidos=len(selecionados), bytes=total_bytes)
        await _auditar(db, admin, "sucesso", metadata)
        return DatasetExportArtifact(arquivo, f"hality-dataset-{uuid.uuid4().hex[:12]}.zip")
    except Exception:
        arquivo.close()
        await _auditar(db, admin, "falha", {**metadata, "motivo": "geracao"})
        raise
