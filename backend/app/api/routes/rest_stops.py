from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbDep
from app.models.rest_stop import RestStop
from app.schemas.rest_stop import RestStopCreate, RestStopResponse, RestStopUpdate

router = APIRouter(prefix="/rest-stops", tags=["rest-stops"])


@router.get("/", response_model=list[RestStopResponse])
async def list_rest_stops(db: DbDep) -> list[RestStop]:
    result = await db.execute(
        select(RestStop).where(RestStop.is_active.is_(True)).order_by(RestStop.id)
    )
    return list(result.scalars())


@router.post("/", response_model=RestStopResponse, status_code=status.HTTP_201_CREATED)
async def create_rest_stop(body: RestStopCreate, db: DbDep) -> RestStop:
    stop = RestStop(**body.model_dump())
    db.add(stop)
    await db.commit()
    await db.refresh(stop)
    return stop


@router.patch("/{stop_id}", response_model=RestStopResponse)
async def update_rest_stop(
    stop_id: int, body: RestStopUpdate, db: DbDep
) -> RestStop:
    result = await db.execute(select(RestStop).where(RestStop.id == stop_id))
    stop = result.scalar_one_or_none()
    if not stop:
        raise HTTPException(status_code=404, detail="휴게소를 찾을 수 없습니다.")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(stop, field, value)
    await db.commit()
    await db.refresh(stop)
    return stop


@router.delete("/{stop_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rest_stop(stop_id: int, db: DbDep) -> None:
    result = await db.execute(select(RestStop).where(RestStop.id == stop_id))
    stop = result.scalar_one_or_none()
    if not stop:
        raise HTTPException(status_code=404, detail="휴게소를 찾을 수 없습니다.")
    stop.is_active = False  # soft delete
    await db.commit()
