from pydantic import BaseModel, Field, model_validator


class DatasetExportCreate(BaseModel):
    diagnostico_ids: list[int] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def ids_unicos(self) -> "DatasetExportCreate":
        if len(self.diagnostico_ids) != len(set(self.diagnostico_ids)):
            raise ValueError("diagnostico_ids não pode conter duplicados")
        if any(diagnostico_id <= 0 for diagnostico_id in self.diagnostico_ids):
            raise ValueError("diagnostico_ids deve conter somente inteiros positivos")
        return self
