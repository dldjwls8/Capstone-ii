from datetime import datetime

from pydantic import BaseModel

from app.models.rest_stop import RestStopType


class RestStopCreate(BaseModel):
    name: str
    type: RestStopType
    latitude: float
    longitude: float


class RestStopUpdate(BaseModel):
    name: str | None = None
    type: RestStopType | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_active: bool | None = None


class RestStopResponse(BaseModel):
    id: int
    name: str
    type: RestStopType
    latitude: float
    longitude: float
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
