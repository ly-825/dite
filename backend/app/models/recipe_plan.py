from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecipePlan(Base):
    """Saved generated C-side recipe plan."""

    __tablename__ = "recipe_plans"
    __table_args__ = (
        Index("idx_recipe_plans_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    source_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    plan_type: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    plan_content_json: Mapped[str] = mapped_column(Text, nullable=False)
    generation_basis_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
