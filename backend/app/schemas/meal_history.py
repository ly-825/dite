from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MealNutritionTotals(BaseModel):
    calories_kcal: int = 0
    protein_g: float = 0
    carbohydrate_g: float = 0
    fat_g: float = 0


class MealRecordResponse(BaseModel):
    id: int
    session_id: str
    recorded_at: datetime
    meal_type: str
    foods: list[dict[str, Any]] = Field(default_factory=list)
    estimated_calories_kcal: int | None = None
    estimated_protein_g: float | None = None
    estimated_carbohydrate_g: float | None = None
    estimated_fat_g: float | None = None
    user_feedback: str | None = None
    analysis_markdown: str


class DailyMealSummary(BaseModel):
    date: str
    meal_count: int
    calories_kcal: int
    protein_g: float
    carbohydrate_g: float
    fat_g: float


class MealHistoryResponse(BaseModel):
    days: int
    records: list[MealRecordResponse] = Field(default_factory=list)
    daily_summaries: list[DailyMealSummary] = Field(default_factory=list)
    totals: MealNutritionTotals
    recent_foods: list[str] = Field(default_factory=list)


class MealReviewResponse(BaseModel):
    days: int
    record_count: int
    days_with_records: int
    totals: MealNutritionTotals
    average_daily_calories_kcal: int
    average_daily_protein_g: float
    average_daily_carbohydrate_g: float
    average_daily_fat_g: float
    recent_foods: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
