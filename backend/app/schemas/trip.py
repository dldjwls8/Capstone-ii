from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from app.models.trip import TripStatus


class WaypointIn(BaseModel):
    name: str
    lat: float
    lon: float


class TripCreate(BaseModel):
    driver_id: int
    vehicle_id: int
    origin_name: str
    origin_lat: float
    origin_lon: float
    dest_name: str
    dest_lat: float
    dest_lon: float
    waypoints: list[WaypointIn] = []


class TripStatusUpdate(BaseModel):
    status: TripStatus


class TripResponse(BaseModel):
    id: int
    driver_id: int
    vehicle_id: int
    origin_name: str
    origin_lat: float
    origin_lon: float
    dest_name: str
    dest_lat: float
    dest_lon: float
    status: TripStatus
    optimized_route: Optional[Any]
    total_driving_seconds: int
    total_rest_seconds: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}
