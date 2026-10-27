from pydantic import BaseModel, Field, field_validator


class DatasetExportRequest(BaseModel):
    diagnostico_ids: list[int] = Field(min_length=1, max_length=1000)

    @field_validator("diagnostico_ids")
    @classmethod
    def ids_unicos_e_positivos(cls, valor: list[int]) -> list[int]:
        if any(item <= 0 for item in valor) or len(set(valor)) != len(valor):
            raise ValueError("diagnostico_ids deve conter IDs positivos e distintos")
        return valor
