from pydantic import BaseModel

from app.models.rest_stop import RestStopType


class RestStopCreate(BaseModel):
    name: str
    type: RestStopType
    latitude: float
    longitude: float
    direction: str | None = None
    scope: str = "private"
    note: str | None = None


class RestStopRead(BaseModel):
    id: int
    name: str
    type: RestStopType
    latitude: float
    longitude: float
    is_active: bool
    direction: str | None
    scope: str
    note: str | None

    model_config = {"from_attributes": True}
