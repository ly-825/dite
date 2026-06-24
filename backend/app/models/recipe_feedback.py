from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecipeFeedback(Base):
    """Dish-level feedback that affects future recommendations."""

    __tablename__ = "recipe_feedbacks"
    __table_args__ = (
        Index("idx_recipe_feedbacks_user_dish", "user_id", "dish_name"),
        Index("idx_recipe_feedbacks_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    recipe_plan_id: Mapped[int | None] = mapped_column(ForeignKey("recipe_plans.id"), nullable=True, index=True)
    dish_name: Mapped[str] = mapped_column(String(120), nullable=False)
    feedback_type: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
