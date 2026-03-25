from datetime import datetime

from pydantic import BaseModel


class DriverCreate(BaseModel):
    user_id: int
    name: str
    license_number: str
    phone: str


class DriverUpdate(BaseModel):
    name: str | None = None
    license_number: str | None = None
    phone: str | None = None


class DriverResponse(BaseModel):
    id: int
    user_id: int
    name: str
    license_number: str
    phone: str
    created_at: datetime

    model_config = {"from_attributes": True}
