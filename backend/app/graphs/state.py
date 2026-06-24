from __future__ import annotations

from typing import TypedDict

from app.schemas.chat import (
    HealthRiskData,
    MealRecordData,
    NutritionAnalysisData,
    RecipeMealItem,
    WorkflowState,
)


class GraphState(TypedDict, total=False):
    """LangGraph 运行时状态。"""

    user_message: str
    session_id: str
    user_id: int | None
    intent: str
    target_agent: str
    route_reason: str
    route_source: str
    report_text: str | None
    report_file_bytes: bytes | None
    report_file_name: str | None
    meal_before_image_bytes: bytes | None
    meal_before_image_name: str | None
    meal_after_image_bytes: bytes | None
    meal_after_image_name: str | None
    uploaded_image_count: int
    workflow_state: WorkflowState
    blocked: bool
    guard_message: str
    report_missing_file: bool
    parsed_report: str | None
    risk: HealthRiskData
    health_risk_reply: str
    nutrition: NutritionAnalysisData
    recipes: list[RecipeMealItem]
    recipe_reply: str
    recommendations: list[str]
    meal_record: MealRecordData | None
    meal_record_reply: str
    diet_history_reply: str
    fallback_reply: str

