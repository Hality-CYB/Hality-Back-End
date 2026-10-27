import io

import pytest
from PIL import Image
from pydantic import ValidationError

from app.schemas.dataset_export import DatasetExportRequest
from app.services.dataset_export_service import _sanitizar_imagem


def _bytes_imagem(imagem: Image.Image, formato: str, **kwargs: object) -> bytes:
    arquivo = io.BytesIO()
    imagem.save(arquivo, format=formato, **kwargs)
    return arquivo.getvalue()


def test_payload_limita_exportacao_a_cem_diagnosticos() -> None:
    with pytest.raises(ValidationError):
        DatasetExportRequest(diagnostico_ids=list(range(1, 102)))


def test_sanitizacao_aplica_orientacao_exif_e_remove_metadados() -> None:
    imagem = Image.new("RGB", (2, 3), "red")
    exif = imagem.getexif()
    exif[274] = 6

    resultado = _sanitizar_imagem(_bytes_imagem(imagem, "JPEG", exif=exif), "image/jpeg")

    with Image.open(io.BytesIO(resultado)) as normalizada:
        assert normalizada.size == (3, 2)
        assert normalizada.getexif().get(274) is None


def test_sanitizacao_webp_preserva_pixels() -> None:
    imagem = Image.new("RGB", (2, 2))
    imagem.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)])

    resultado = _sanitizar_imagem(_bytes_imagem(imagem, "PNG"), "image/webp")

    with Image.open(io.BytesIO(resultado)) as normalizada:
        pixels_esperados = [imagem.getpixel((x, y)) for y in range(2) for x in range(2)]
        pixels_obtidos = [normalizada.getpixel((x, y)) for y in range(2) for x in range(2)]
        assert pixels_obtidos == pixels_esperados
