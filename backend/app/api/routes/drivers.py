from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbDep
from app.models.driver import Driver
from app.schemas.driver import DriverCreate, DriverResponse, DriverUpdate

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.get("/", response_model=list[DriverResponse])
async def list_drivers(db: DbDep) -> list[Driver]:
    result = await db.execute(select(Driver).order_by(Driver.id))
    return list(result.scalars())


@router.post("/", response_model=DriverResponse, status_code=status.HTTP_201_CREATED)
async def create_driver(body: DriverCreate, db: DbDep) -> Driver:
    driver = Driver(**body.model_dump())
    db.add(driver)
    await db.commit()
    await db.refresh(driver)
    return driver


@router.get("/{driver_id}", response_model=DriverResponse)
async def get_driver(driver_id: int, db: DbDep) -> Driver:
    result = await db.execute(select(Driver).where(Driver.id == driver_id))
    driver = result.scalar_one_or_none()
    if not driver:
        raise HTTPException(status_code=404, detail="운전자를 찾을 수 없습니다.")
    return driver


@router.patch("/{driver_id}", response_model=DriverResponse)
async def update_driver(driver_id: int, body: DriverUpdate, db: DbDep) -> Driver:
    result = await db.execute(select(Driver).where(Driver.id == driver_id))
    driver = result.scalar_one_or_none()
    if not driver:
        raise HTTPException(status_code=404, detail="운전자를 찾을 수 없습니다.")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(driver, field, value)
    await db.commit()
    await db.refresh(driver)
    return driver
