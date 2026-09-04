from datetime import datetime

from pydantic import BaseModel


class ImagemCreate(BaseModel):
    diagnostico_id: int
    url_arquivo: str
    ordem: int


class ImagemDetail(BaseModel):
    """Um diagnostico pode ter mais de uma imagem."""

    id: int
    diagnostico_id: int
    url_arquivo: str
    ordem: int
    data_captura: datetime