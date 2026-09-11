from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class UserRole(StrEnum):
    ADMIN = "admin"
    PROFESSIONAL = "professional"
    PATIENT = "patient"


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    phone: str | None = None
    role: UserRole
    is_active: bool
    created_at: datetime
