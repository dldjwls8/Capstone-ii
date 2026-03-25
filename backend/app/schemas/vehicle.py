from datetime import datetime

from pydantic import BaseModel, Field


class VehicleCreate(BaseModel):
    plate_number: str = Field(..., examples=["12가3456"])
    vehicle_type: str = Field(..., examples=["5톤카고"])
    height_m: float = Field(..., gt=0, le=5.0)
    weight_kg: float = Field(..., gt=0, le=50_000)


class VehicleUpdate(BaseModel):
    vehicle_type: str | None = None
    height_m: float | None = Field(default=None, gt=0, le=5.0)
    weight_kg: float | None = Field(default=None, gt=0, le=50_000)
    is_active: bool | None = None


class VehicleResponse(BaseModel):
    id: int
    plate_number: str
    vehicle_type: str
    height_m: float
    weight_kg: float
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
