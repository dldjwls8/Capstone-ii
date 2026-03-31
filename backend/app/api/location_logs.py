from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.location_log import DrivingState, LocationLog
from app.models.trip import Trip
from app.schemas.location_log import LocationLogCreate, LocationLogRead

router = APIRouter()

# 정체 판단 속도 임계값 (km/h)
_TRAFFIC_STOP_KMH: float = 5.0


def classify_driving_state(speed_kmh: float | None) -> DrivingState:
    """speed_kmh 기반으로 주행 상태를 자동 판정합니다.

    판정 규칙:
      - None           → unknown  (GPS 수신 불가 등)
      - 0 ~ 5 km/h    → traffic_stop  (정체·완전 정지)
      - 5 km/h 초과   → driving

    resting 상태는 기사 앱이 명시적으로 전송해야 합니다.
    (휴게소 진입 등 의도적 정차와 정체를 속도만으로 구분 불가)
    """
    if speed_kmh is None:
        return DrivingState.unknown
    if speed_kmh <= _TRAFFIC_STOP_KMH:
        return DrivingState.traffic_stop
    return DrivingState.driving


@router.post("/", response_model=LocationLogRead, status_code=201)
async def create_location_log(
    body: LocationLogCreate, db: AsyncSession = Depends(get_db)
):
    """기사 앱이 주기적으로 GPS 위치를 전송하는 엔드포인트.

    state 가 unknown 이고 speed_kmh 가 제공된 경우 자동으로 주행 상태를 판정합니다.
    """
    trip = await db.get(Trip, body.trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    data = body.model_dump()
    if data["state"] == DrivingState.unknown and data["speed_kmh"] is not None:
        data["state"] = classify_driving_state(data["speed_kmh"])

    log = LocationLog(**data)
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


@router.get("/{trip_id}", response_model=list[LocationLogRead])
async def list_location_logs(trip_id: int, db: AsyncSession = Depends(get_db)):
    """관제 웹이 특정 운행의 위치 이력을 조회하는 엔드포인트."""
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    result = await db.execute(
        select(LocationLog)
        .where(LocationLog.trip_id == trip_id)
        .order_by(LocationLog.recorded_at)
    )
    return result.scalars().all()
