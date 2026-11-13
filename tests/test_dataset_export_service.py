import asyncio
import csv
import io
import threading
import uuid
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from app.api.v1.endpoints import admin_dataset_exports
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
        sha256=None,
    )
    label = SimpleNamespace(codigo=code, nome_exibicao=code.replace("_", " "))
    return dataset_export_service._Candidate(
        diagnostico_id=version,
        paciente_id=uuid.uuid4(),
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
    candidatos[0].label.nome_exibicao = 'Hálito; "íntimo"'
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
        manifest = arquivo.read("manifest.csv")
        assert manifest.startswith(b"\xef\xbb\xbf")
        linhas = list(csv.DictReader(io.StringIO(manifest.decode("utf-8-sig")), delimiter=";"))
        assert "ponto e vírgula" in arquivo.read("README.md").decode("utf-8-sig")

    assert "README.md" in nomes
    assert len(linhas) == 2
    assert {linha["label_source"] for linha in linhas} == {"hality", "profissional"}
    assert {linha["label_code"] for linha in linhas} == {"halitose_intima", "halito_normal"}
    assert linhas[0]["label_name"] == 'Hálito; "íntimo"'
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


async def test_gerar_rejeita_imagem_cujo_sha_original_diverge_do_banco(monkeypatch) -> None:
    candidato = _candidate(code="halito_normal", source="hality", version=1, url="/a.png")
    candidato.images[0].sha256 = "0" * 64
    monkeypatch.setattr(dataset_export_service, "_candidates", AsyncMock(return_value=[candidato]))
    monkeypatch.setattr(
        dataset_export_service.diagnostico_storage,
        "ler_privado",
        AsyncMock(return_value=_png_bytes()),
    )
    monkeypatch.setattr(
        dataset_export_service.auditoria_queries, "registrar_acesso", _sem_auditoria
    )

    with pytest.raises(dataset_export_service.DatasetExportStorageError):
        await dataset_export_service.gerar(AsyncMock(), ADMIN, [1], _settings(), "sha-invalido")


async def test_gerar_delega_recodificacao_e_compactacao_para_threads(monkeypatch) -> None:
    candidato = _candidate(code="halito_normal", source="hality", version=1, url="/a.png")
    monkeypatch.setattr(
        dataset_export_service,
        "_candidates",
        AsyncMock(side_effect=[[candidato], [candidato]]),
    )
    monkeypatch.setattr(
        dataset_export_service.diagnostico_storage,
        "ler_privado",
        AsyncMock(return_value=_png_bytes()),
    )
    monkeypatch.setattr(
        dataset_export_service.auditoria_queries, "registrar_acesso", _sem_auditoria
    )
    original_to_thread = asyncio.to_thread
    chamadas = []

    async def registrar(func, *args, **kwargs):
        chamadas.append(func)
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(dataset_export_service.asyncio, "to_thread", registrar)

    spool = await dataset_export_service.gerar(AsyncMock(), ADMIN, [1], _settings(), "fora-do-loop")

    assert dataset_export_service._derivar_imagem in chamadas
    assert any(getattr(func, "__name__", "") == "writestr" for func in chamadas)
    spool.close()


async def test_em_thread_aguarda_escrita_terminar_antes_de_propagar_cancelamento() -> None:
    iniciou = threading.Event()
    liberar = threading.Event()

    def bloqueante() -> None:
        iniciou.set()
        liberar.wait()

    task = asyncio.create_task(dataset_export_service._em_thread(bloqueante))
    while not iniciou.is_set():
        await asyncio.sleep(0)

    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()

    liberar.set()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_stream_entrega_tudo_e_fecha_o_spool() -> None:
    spool = io.BytesIO(b"conteudo")

    chunks = [chunk async for chunk in admin_dataset_exports._stream_and_cleanup(spool)]

    assert b"".join(chunks) == b"conteudo"
    assert spool.closed


async def test_stream_interrompido_fecha_o_spool() -> None:
    spool = io.BytesIO(b"conteudo")
    stream = admin_dataset_exports._stream_and_cleanup(spool)

    assert await anext(stream) == b"conteudo"
    await stream.aclose()

    assert spool.closed


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


async def test_sem_exif_mantem_qualidade_alta_no_jpeg() -> None:
    entrada = io.BytesIO()
    Image.effect_noise((32, 32), 64).convert("RGB").save(entrada, format="JPEG", quality=95)

    exportada = dataset_export_service._sem_exif(entrada.getvalue(), "image/jpeg")

    with Image.open(io.BytesIO(exportada)) as resultado:
        # Qualidade 95 tem tabela de quantização com valores baixos; o padrão
        # do Pillow (75) passa de 20 e degradaria a foto a cada exportação.
        assert max(resultado.quantization[0]) < 20


async def test_sem_exif_preserva_os_pixels_do_webp() -> None:
    original = Image.effect_noise((16, 16), 64).convert("RGB")
    entrada = io.BytesIO()
    original.save(entrada, format="WEBP", lossless=True)

    exportada = dataset_export_service._sem_exif(entrada.getvalue(), "image/webp")

    with Image.open(io.BytesIO(exportada)) as resultado:
        assert resultado.convert("RGB").tobytes() == original.tobytes()


async def test_content_type_ausente_e_reconhecido_pelo_cabecalho() -> None:
    jpeg = io.BytesIO()
    Image.new("RGB", (1, 1), "red").save(jpeg, format="JPEG")
    sem_tipo = SimpleNamespace(content_type=None)

    assert dataset_export_service._content_type(sem_tipo, jpeg.getvalue()) == "image/jpeg"
    assert dataset_export_service._content_type(sem_tipo, _png_bytes()) == "image/png"
    with pytest.raises(dataset_export_service.DatasetExportStorageError):
        dataset_export_service._content_type(sem_tipo, b"nao e imagem")
