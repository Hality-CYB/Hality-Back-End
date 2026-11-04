import asyncio
import csv
import io
import uuid
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from app.services import dataset_export_service

pytestmark = pytest.mark.asyncio


ADMIN = SimpleNamespace(id=uuid.uuid4())


def _settings(max_bytes: int = 1024 * 1024) -> SimpleNamespace:
    return SimpleNamespace(
        dataset_export_enabled=True, dataset_export_max_items=10, dataset_export_max_bytes=max_bytes
    )


def _candidate(*, code: str, source: str, version: int, url: str) -> object:
    image = SimpleNamespace(
        url_arquivo=url,
        content_type="image/png",
        ordem=1,
        sha256="stored-sha",
    )
    label = SimpleNamespace(codigo=code, nome_exibicao=code.replace("_", " "))
    return dataset_export_service._Candidate(
        diagnostico_id=version,
        images=(image,),
        label=label,
        label_source=source,
        label_version=version,
        consent_version="v1",
    )


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (1, 1), "red").save(output, format="PNG")
    return output.getvalue()


async def _sem_auditoria(*args, **kwargs) -> None:
    return None


async def test_gerar_escreve_zip_manifesto_imagens_e_precedencia_dos_rotulos(
    monkeypatch,
) -> None:
    candidatos = [
        _candidate(code="halitose_intima", source="hality", version=2, url="/hality.png"),
        _candidate(code="halito_normal", source="profissional", version=1, url="/prof.png"),
    ]
    imagem = _png_bytes()
    monkeypatch.setattr(
        dataset_export_service,
        "_candidates",
        AsyncMock(side_effect=[candidatos, candidatos]),
    )
    leitura = AsyncMock(return_value=imagem)
    monkeypatch.setattr(dataset_export_service.diagnostico_storage, "ler_privado", leitura)
    monkeypatch.setattr(
        dataset_export_service.auditoria_queries, "registrar_acesso", _sem_auditoria
    )

    spool = await dataset_export_service.gerar(AsyncMock(), ADMIN, [2, 1], _settings(), "corr-1")
    with zipfile.ZipFile(spool) as arquivo:
        nomes = set(arquivo.namelist())
        linhas = list(csv.DictReader(io.StringIO(arquivo.read("manifest.csv").decode())))

    assert "README.md" in nomes
    assert len(linhas) == 2
    assert {linha["label_source"] for linha in linhas} == {"hality", "profissional"}
    assert {linha["label_code"] for linha in linhas} == {"halitose_intima", "halito_normal"}
    assert all(linha["image_path"] in nomes for linha in linhas)
    assert leitura.await_count == 4
    spool.close()


async def test_sem_exif_aplica_orientacao_antes_de_remover_exif() -> None:
    original = io.BytesIO()
    imagem = Image.new("RGB", (2, 1), "red")
    exif = Image.Exif()
    exif[274] = 6
    imagem.save(original, format="JPEG", exif=exif)

    exportada = dataset_export_service._sem_exif(original.getvalue(), "image/jpeg")

    with Image.open(io.BytesIO(exportada)) as resultado:
        assert resultado.size == (1, 2)
        assert resultado.getexif().get(274) is None


async def test_gerar_revalida_consentimento_apos_montar_zip(monkeypatch) -> None:
    candidato = _candidate(code="halito_normal", source="hality", version=1, url="/a.png")
    revogado = dataset_export_service.DatasetExportError
    monkeypatch.setattr(
        dataset_export_service,
        "_candidates",
        AsyncMock(side_effect=[[candidato], revogado]),
    )
    monkeypatch.setattr(
        dataset_export_service.diagnostico_storage,
        "ler_privado",
        AsyncMock(return_value=_png_bytes()),
    )
    auditoria = AsyncMock()
    monkeypatch.setattr(dataset_export_service.auditoria_queries, "registrar_acesso", auditoria)

    with pytest.raises(dataset_export_service.DatasetExportError):
        await dataset_export_service.gerar(AsyncMock(), ADMIN, [1], _settings(), "corr-2")

    assert auditoria.await_count == 1


async def test_gerar_interrompe_ao_exceder_limite_antes_da_segunda_leitura(monkeypatch) -> None:
    candidato = _candidate(code="halito_normal", source="hality", version=1, url="/a.png")
    monkeypatch.setattr(
        dataset_export_service,
        "_candidates",
        AsyncMock(return_value=[candidato]),
    )
    leitura = AsyncMock(return_value=_png_bytes())
    monkeypatch.setattr(dataset_export_service.diagnostico_storage, "ler_privado", leitura)
    monkeypatch.setattr(
        dataset_export_service.auditoria_queries, "registrar_acesso", _sem_auditoria
    )

    with pytest.raises(dataset_export_service.DatasetExportLimitError):
        await dataset_export_service.gerar(AsyncMock(), ADMIN, [1], _settings(1), "corr-3")

    assert leitura.await_count == 1


async def test_gerar_converte_falha_de_storage_e_audita(monkeypatch) -> None:
    candidato = _candidate(code="halito_normal", source="hality", version=1, url="/a.png")
    monkeypatch.setattr(dataset_export_service, "_candidates", AsyncMock(return_value=[candidato]))
    monkeypatch.setattr(
        dataset_export_service.diagnostico_storage,
        "ler_privado",
        AsyncMock(side_effect=OSError("storage indisponivel")),
    )
    auditoria = AsyncMock()
    monkeypatch.setattr(dataset_export_service.auditoria_queries, "registrar_acesso", auditoria)

    with pytest.raises(dataset_export_service.DatasetExportStorageError):
        await dataset_export_service.gerar(AsyncMock(), ADMIN, [1], _settings(), "corr-4")

    auditoria.assert_awaited_once()
    assert auditoria.await_args.kwargs["result"] == "falha"


async def test_cancelamento_fecha_spool_e_desfaz_transacao(monkeypatch):
    candidato = _candidate(code="halito_normal", source="hality", version=1, url="/a.png")
    monkeypatch.setattr(
        dataset_export_service,
        "_candidates",
        AsyncMock(side_effect=[[candidato], asyncio.CancelledError()]),
    )
    monkeypatch.setattr(
        dataset_export_service.diagnostico_storage,
        "ler_privado",
        AsyncMock(return_value=_png_bytes()),
    )
    spool = io.BytesIO()
    monkeypatch.setattr(
        dataset_export_service.tempfile, "SpooledTemporaryFile", lambda **kwargs: spool
    )
    db = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await dataset_export_service.gerar(db, ADMIN, [1], _settings(), "cancelamento")
    assert spool.closed
    db.rollback.assert_awaited_once()


async def test_relabel_durante_geracao_aborta_pacote(monkeypatch):
    anterior = _candidate(code="halito_normal", source="hality", version=1, url="/a.png")
    atual = _candidate(code="halitose_intima", source="hality", version=2, url="/a.png")
    monkeypatch.setattr(
        dataset_export_service, "_candidates", AsyncMock(side_effect=[[anterior], [atual]])
    )
    monkeypatch.setattr(
        dataset_export_service.diagnostico_storage,
        "ler_privado",
        AsyncMock(return_value=_png_bytes()),
    )
    auditoria = AsyncMock()
    monkeypatch.setattr(dataset_export_service.auditoria_queries, "registrar_acesso", auditoria)
    with pytest.raises(dataset_export_service.DatasetExportError):
        await dataset_export_service.gerar(AsyncMock(), ADMIN, [1], _settings(), "relabel")
    assert auditoria.await_args.kwargs["result"] == "falha"
