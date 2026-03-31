from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.rest_stop import RestStop
from app.schemas.rest_stop import RestStopCreate, RestStopRead

router = APIRouter()


@router.get("/", response_model=list[RestStopRead])
async def list_rest_stops(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RestStop).where(RestStop.is_active == True))  # noqa: E712
    return result.scalars().all()


@router.post("/", response_model=RestStopRead, status_code=201)
async def create_rest_stop(body: RestStopCreate, db: AsyncSession = Depends(get_db)):
    stop = RestStop(**body.model_dump())
    db.add(stop)
    await db.commit()
    await db.refresh(stop)
    return stop


@router.delete("/{stop_id}", status_code=204)
async def deactivate_rest_stop(stop_id: int, db: AsyncSession = Depends(get_db)):
    stop = await db.get(RestStop, stop_id)
    if not stop:
        raise HTTPException(status_code=404, detail="RestStop not found")
    stop.is_active = False
    await db.commit()
