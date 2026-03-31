from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.trip import Trip
from app.schemas.trip import TripCreate, TripRead, TripStatusPatch

router = APIRouter()


@router.get("/", response_model=list[TripRead])
async def list_trips(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Trip))
    return result.scalars().all()


@router.post("/", response_model=TripRead, status_code=201)
async def create_trip(body: TripCreate, db: AsyncSession = Depends(get_db)):
    data = body.model_dump()
    # waypoints는 list[dict]으로 직렬화
    if data.get("waypoints"):
        data["waypoints"] = [w for w in data["waypoints"]]
    trip = Trip(**data)
    db.add(trip)
    await db.commit()
    await db.refresh(trip)
    return trip


@router.get("/{trip_id}", response_model=TripRead)
async def get_trip(trip_id: int, db: AsyncSession = Depends(get_db)):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


@router.patch("/{trip_id}/status", response_model=TripRead)
async def patch_trip_status(
    trip_id: int, body: TripStatusPatch, db: AsyncSession = Depends(get_db)
):
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    trip.status = body.status
    await db.commit()
    await db.refresh(trip)
    return trip
