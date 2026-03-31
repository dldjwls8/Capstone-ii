import enum

from sqlalchemy import Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy import DateTime

from app.core.database import Base


class DispatchGroupStatus(str, enum.Enum):
    draft       = "draft"
    dispatched  = "dispatched"
    in_progress = "in_progress"
    completed   = "completed"
    cancelled   = "cancelled"


class DispatchGroup(Base):
    __tablename__ = "dispatch_groups"

    id:           Mapped[int]      = mapped_column(primary_key=True)
    admin_id:     Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    title:        Mapped[str]      = mapped_column(String(200), nullable=False)
    scheduled_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    note:         Mapped[str | None]      = mapped_column(Text)
    status:       Mapped[DispatchGroupStatus] = mapped_column(
        SAEnum(DispatchGroupStatus, name="dispatchgroupstatus"),
        nullable=False,
        default=DispatchGroupStatus.draft,
    )
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
