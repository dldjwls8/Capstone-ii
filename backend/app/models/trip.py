import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class TripStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Trip(TimestampMixin, Base):
    """하나의 운행 건을 표현합니다.
    
    배차 단계에서 최적 경로(optimized_route)가 계산되어 저장됩니다.
    """

    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), index=True, nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True, nullable=False)

    # 출·도착 정보
    origin_name: Mapped[str] = mapped_column(String(200), nullable=False)
    origin_lat: Mapped[float] = mapped_column(Float, nullable=False)
    origin_lon: Mapped[float] = mapped_column(Float, nullable=False)
    dest_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dest_lat: Mapped[float] = mapped_column(Float, nullable=False)
    dest_lon: Mapped[float] = mapped_column(Float, nullable=False)

    # 경로 / 상태
    optimized_route: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[TripStatus] = mapped_column(
        Enum(TripStatus, name="tripstatus"), default=TripStatus.SCHEDULED, nullable=False
    )

    # 운행 시간 누적 (초)
    total_driving_seconds: Mapped[int] = mapped_column(Integer, default=0)
    total_rest_seconds: Mapped[int] = mapped_column(Integer, default=0)

    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # relationships
    driver: Mapped["Driver"] = relationship("Driver", back_populates="trips")       # noqa: F821
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="trips")    # noqa: F821
