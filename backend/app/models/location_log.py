import enum

from sqlalchemy import Enum as SAEnum, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy import DateTime

from app.core.database import Base


class DrivingState(str, enum.Enum):
    driving = "driving"
    resting = "resting"
    traffic_stop = "traffic_stop"
    unknown = "unknown"


class LocationLog(Base):
    __tablename__ = "location_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    speed_kmh: Mapped[float | None] = mapped_column(Float)
    state: Mapped[DrivingState] = mapped_column(
        SAEnum(DrivingState, name="drivingstate"),
        nullable=False,
        default=DrivingState.unknown,
    )
    recorded_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
