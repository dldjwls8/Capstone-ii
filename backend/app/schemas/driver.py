from pydantic import BaseModel


class DriverCreate(BaseModel):
    user_id: int
    name: str
    license_number: str | None = None
    phone: str | None = None
    company_id: int | None = None


class DriverRead(BaseModel):
    id: int
    user_id: int
    name: str
    license_number: str | None
    phone: str | None
    company_id: int | None

    model_config = {"from_attributes": True}
