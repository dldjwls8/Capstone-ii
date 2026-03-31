from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.vehicle import Vehicle
from app.schemas.vehicle import VehicleCreate, VehiclePatch, VehicleRead

router = APIRouter()


@router.get("/", response_model=list[VehicleRead])
async def list_vehicles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Vehicle).where(Vehicle.is_active == True))  # noqa: E712
    return result.scalars().all()


@router.post("/", response_model=VehicleRead, status_code=201)
async def create_vehicle(body: VehicleCreate, db: AsyncSession = Depends(get_db)):
    vehicle = Vehicle(**body.model_dump())
    db.add(vehicle)
    await db.commit()
    await db.refresh(vehicle)
    return vehicle


@router.patch("/{vehicle_id}", response_model=VehicleRead)
async def patch_vehicle(
    vehicle_id: int, body: VehiclePatch, db: AsyncSession = Depends(get_db)
):
    vehicle = await db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(vehicle, field, value)
    await db.commit()
    await db.refresh(vehicle)
    return vehicle
