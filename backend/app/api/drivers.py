from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.driver import Driver
from app.schemas.driver import DriverCreate, DriverRead

router = APIRouter()


@router.get("/", response_model=list[DriverRead])
async def list_drivers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Driver))
    return result.scalars().all()


@router.post("/", response_model=DriverRead, status_code=201)
async def create_driver(body: DriverCreate, db: AsyncSession = Depends(get_db)):
    driver = Driver(**body.model_dump())
    db.add(driver)
    await db.commit()
    await db.refresh(driver)
    return driver
