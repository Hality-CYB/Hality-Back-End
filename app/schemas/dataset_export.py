from pydantic import BaseModel, Field


class DatasetExportRequest(BaseModel):
    diagnostico_ids: list[int] = Field(min_length=1)
