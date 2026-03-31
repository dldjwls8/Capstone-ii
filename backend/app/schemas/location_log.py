from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.location_log import DrivingState


class LocationLogCreate(BaseModel):
    trip_id: int
    latitude: float
    longitude: float
    speed_kmh: Optional[float] = None
    state: DrivingState = DrivingState.unknown


class LocationLogRead(BaseModel):
    id: int
    trip_id: int
    latitude: float
    longitude: float
    speed_kmh: Optional[float]
    state: DrivingState
    recorded_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
