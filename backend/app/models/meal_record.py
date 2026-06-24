from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MealRecord(Base):
    __tablename__ = "meal_records"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    meal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    foods_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_calories_kcal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_protein_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_carbohydrate_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_fat_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_feedback: Mapped[str | None] = mapped_column(String(64), nullable=True)
    analysis_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
