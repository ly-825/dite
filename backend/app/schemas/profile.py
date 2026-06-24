from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MemoryType = Literal["goal", "allergy", "taboo", "preference", "health_concern"]
MemoryStatus = Literal["pending", "confirmed", "rejected"]
RecipeFeedbackType = Literal["like", "dislike", "unavailable", "too_complex"]


class UserProfilePayload(BaseModel):
    age: int | None = Field(default=None, ge=1, le=120)
    gender: str | None = Field(default=None, max_length=20)
    height_cm: float | None = Field(default=None, ge=50, le=260)
    weight_kg: float | None = Field(default=None, ge=10, le=400)
    goal: str = Field(default="", max_length=80)
    allergies: list[str] = Field(default_factory=list)
    taboos: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    health_concerns: list[str] = Field(default_factory=list)
    has_medical_report: bool = False
    medical_report_text: str | None = None


class UserProfileUpdate(BaseModel):
    age: int | None = Field(default=None, ge=1, le=120)
    gender: str | None = Field(default=None, max_length=20)
    height_cm: float | None = Field(default=None, ge=50, le=260)
    weight_kg: float | None = Field(default=None, ge=10, le=400)
    goal: str = Field(default="", max_length=80)
    allergies: list[str] = Field(default_factory=list)
    taboos: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    health_concerns: list[str] = Field(default_factory=list)


class UserMemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    memory_type: MemoryType
    content: str
    source: str
    status: MemoryStatus
    source_session_id: str | None = None
    created_at: datetime
    updated_at: datetime


class RecipePlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_session_id: str | None = None
    plan_type: str
    plan_content: dict
    generation_basis: dict
    created_at: datetime


class RecipeFeedbackCreate(BaseModel):
    recipe_plan_id: int | None = None
    dish_name: str = Field(min_length=1, max_length=120)
    feedback_type: RecipeFeedbackType
    comment: str | None = Field(default=None, max_length=500)


class RecipeFeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recipe_plan_id: int | None = None
    dish_name: str
    feedback_type: RecipeFeedbackType
    comment: str | None = None
    created_at: datetime


class UserProfileResponse(BaseModel):
    profile: UserProfilePayload
    pending_memories: list[UserMemoryResponse] = Field(default_factory=list)
    confirmed_memories: list[UserMemoryResponse] = Field(default_factory=list)
    recipe_plans: list[RecipePlanResponse] = Field(default_factory=list)
    recipe_feedbacks: list[RecipeFeedbackResponse] = Field(default_factory=list)
