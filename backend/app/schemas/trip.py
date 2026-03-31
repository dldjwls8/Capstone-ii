from pydantic import BaseModel

from app.models.trip import TripStatus


class WaypointSchema(BaseModel):
    name: str
    lat: float
    lon: float


class TripCreate(BaseModel):
    driver_id: int
    vehicle_id: int
    dest_name: str
    dest_lat: float
    dest_lon: float
    waypoints: list[WaypointSchema] | None = None
    vehicle_height_m: float | None = None
    vehicle_weight_kg: float | None = None
    vehicle_length_cm: float | None = None
    vehicle_width_cm: float | None = None
    departure_time: str | None = None  # ISO-8601


class TripStatusPatch(BaseModel):
    status: TripStatus


class TripRead(BaseModel):
    id: int
    driver_id: int
    vehicle_id: int
    origin_name: str | None
    origin_lat: float | None
    origin_lon: float | None
    dest_name: str
    dest_lat: float
    dest_lon: float
    waypoints: list[WaypointSchema] | None
    departure_time: str | None
    optimized_route: dict | None
    status: TripStatus
    total_driving_seconds: int
    total_rest_seconds: int

    model_config = {"from_attributes": True}
