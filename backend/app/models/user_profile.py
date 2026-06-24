from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserProfile(Base):
    """用户长期画像和体检报告缓存。"""

    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False, index=True)
    goal: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    allergy_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    taboo_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    health_concerns_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    medical_report_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
