from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.meal_record import MealRecord
from app.models.recipe_feedback import RecipeFeedback
from app.models.recipe_plan import RecipePlan
from app.models.user_memory import UserMemory
from app.models.user_profile import UserProfile
from app.schemas.profile import (
    RecipeFeedbackCreate,
    RecipeFeedbackResponse,
    RecipePlanResponse,
    UserMemoryResponse,
    UserProfilePayload,
    UserProfileResponse,
    UserProfileUpdate,
)
from app.services.llm_service import llm_service


@dataclass(frozen=True)
class MemoryCandidate:
    memory_type: str
    content: str


@dataclass
class RecommendationContext:
    goal: str = ""
    allergies: list[str] = field(default_factory=list)
    taboos: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    health_concerns: list[str] = field(default_factory=list)
    disliked_dishes: list[str] = field(default_factory=list)
    liked_dishes: list[str] = field(default_factory=list)
    recent_meals: list[dict[str, Any]] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "allergies": self.allergies,
            "taboos": self.taboos,
            "preferences": self.preferences,
            "health_concerns": self.health_concerns,
            "disliked_dishes": self.disliked_dishes,
            "liked_dishes": self.liked_dishes,
            "recent_meals": self.recent_meals,
        }


def normalize_tags(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value).strip().split())
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _loads_list(payload: str | None) -> list[str]:
    if not payload:
        return []
    try:
        value = json.loads(payload)
    except Exception:
        return []
    if not isinstance(value, list):
        return []
    return normalize_tags(value)


class CSideProfileService:
    def get_or_create_profile(self, *, db: Session, user_id: int) -> UserProfile:
        profile = db.execute(select(UserProfile).where(UserProfile.user_id == user_id)).scalar_one_or_none()
        if profile is not None:
            return profile
        profile = UserProfile(
            user_id=user_id,
            allergy_json="[]",
            taboo_json="[]",
            diet_preference_json="[]",
            health_concerns_json="[]",
        )
        db.add(profile)
        db.flush()
        return profile

    def get_profile_bundle(self, *, db: Session, user_id: int) -> UserProfileResponse:
        profile = self.get_or_create_profile(db=db, user_id=user_id)
        pending = self._list_memories(db=db, user_id=user_id, status="pending")
        confirmed = self._list_memories(db=db, user_id=user_id, status="confirmed")
        plans = self._list_recipe_plans(db=db, user_id=user_id)
        feedbacks = self._list_recipe_feedbacks(db=db, user_id=user_id)
        return UserProfileResponse(
            profile=self._profile_payload(profile),
            pending_memories=[UserMemoryResponse.model_validate(item) for item in pending],
            confirmed_memories=[UserMemoryResponse.model_validate(item) for item in confirmed],
            recipe_plans=[self._plan_response(item) for item in plans],
            recipe_feedbacks=[RecipeFeedbackResponse.model_validate(item) for item in feedbacks],
        )

    def update_profile(self, *, db: Session, user_id: int, payload: UserProfileUpdate) -> UserProfileResponse:
        profile = self.get_or_create_profile(db=db, user_id=user_id)
        profile.age = payload.age
        profile.gender = payload.gender.strip() if payload.gender else None
        profile.height_cm = payload.height_cm
        profile.weight_kg = payload.weight_kg
        profile.goal = payload.goal.strip()
        profile.allergy_json = json.dumps(normalize_tags(payload.allergies), ensure_ascii=False)
        profile.taboo_json = json.dumps(normalize_tags(payload.taboos), ensure_ascii=False)
        profile.diet_preference_json = json.dumps(normalize_tags(payload.preferences), ensure_ascii=False)
        profile.health_concerns_json = json.dumps(normalize_tags(payload.health_concerns), ensure_ascii=False)
        profile.updated_at = datetime.now()
        db.commit()
        return self.get_profile_bundle(db=db, user_id=user_id)

    def extract_memory_candidates(self, text: str) -> list[MemoryCandidate]:
        content = " ".join(text.strip().split())
        if not content:
            return []

        llm_candidates = llm_service.extract_user_memory_candidates(user_message=content)
        if llm_candidates is not None:
            return self._dedupe_memory_candidates(self._normalize_llm_memory_candidates(llm_candidates))

        return self._extract_rule_memory_candidates(content)

    def _extract_rule_memory_candidates(self, content: str) -> list[MemoryCandidate]:
        candidates: list[MemoryCandidate] = []
        patterns = [
            ("allergy", r"(?:我)?对([\u4e00-\u9fa5A-Za-z0-9]{1,12})过敏"),
            ("allergy", r"(?:^|[，。,.\s])([\u4e00-\u9fa5A-Za-z0-9]{1,12})过敏"),
            ("taboo", r"我不吃([\u4e00-\u9fa5A-Za-z0-9]{1,12})"),
            ("taboo", r"不要(?:再)?给我推荐([\u4e00-\u9fa5A-Za-z0-9]{1,12})"),
            ("preference", r"我喜欢([\u4e00-\u9fa5A-Za-z0-9]{1,12})"),
            ("preference", r"我爱吃([\u4e00-\u9fa5A-Za-z0-9]{1,12})"),
            ("goal", r"(?:我想|目标是)(减脂|增肌|控糖|均衡饮食)"),
            ("health_concern", r"我(?:的)?(血糖偏高|血脂偏高|尿酸偏高|血压偏高)"),
        ]
        for memory_type, pattern in patterns:
            for match in re.finditer(pattern, content):
                value = match.group(1).strip("，。,. ")
                if memory_type == "allergy":
                    value = re.sub(r"^(?:也)?对", "", value)
                if value:
                    candidates.append(MemoryCandidate(memory_type=memory_type, content=value))

        return self._dedupe_memory_candidates(candidates)

    def _normalize_llm_memory_candidates(self, raw_items: list[dict[str, str]]) -> list[MemoryCandidate]:
        allowed_types = {"goal", "allergy", "taboo", "preference", "health_concern"}
        candidates: list[MemoryCandidate] = []
        for item in raw_items:
            memory_type = str(item.get("type") or item.get("memory_type") or "").strip().lower()
            content = self._normalize_memory_content(str(item.get("content") or "").strip())
            if memory_type not in allowed_types or not content:
                continue
            candidates.append(MemoryCandidate(memory_type=memory_type, content=content))
        return candidates

    def _normalize_memory_content(self, value: str) -> str:
        text = value.strip(" \t\r\n，。,.；;：:、")
        text = re.sub(r"^(?:我(?:不|很)?(?:喜欢|爱)?吃?|对|不要(?:再)?给我推荐)", "", text)
        text = text.strip(" \t\r\n，。,.；;：:、")
        if not text or len(text) > 40:
            return ""
        return text

    def _dedupe_memory_candidates(self, candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
        unique: list[MemoryCandidate] = []
        seen: set[tuple[str, str]] = set()
        for item in candidates:
            key = (item.memory_type, item.content)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def save_chat_memories(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        text: str,
        candidates: list[MemoryCandidate] | None = None,
    ) -> list[UserMemory]:
        saved: list[UserMemory] = []
        for candidate in candidates if candidates is not None else self.extract_memory_candidates(text):
            existed = db.execute(
                select(UserMemory).where(
                    UserMemory.user_id == user_id,
                    UserMemory.memory_type == candidate.memory_type,
                    UserMemory.content == candidate.content,
                    UserMemory.status.in_(["pending", "confirmed", "rejected"]),
                )
            ).scalar_one_or_none()
            if existed is not None:
                continue
            row = UserMemory(
                user_id=user_id,
                memory_type=candidate.memory_type,
                content=candidate.content,
                source="chat",
                status="confirmed",
                source_session_id=session_id,
            )
            db.add(row)
            self._apply_memory_to_profile(db=db, user_id=user_id, memory=row)
            saved.append(row)
        if saved:
            db.flush()
        return saved

    def confirm_memory(self, *, db: Session, user_id: int, memory_id: int) -> UserProfileResponse:
        memory = self._get_memory_for_user(db=db, user_id=user_id, memory_id=memory_id)
        if memory.status != "pending":
            raise HTTPException(status_code=400, detail="只能确认待确认记忆")
        memory.status = "confirmed"
        memory.updated_at = datetime.now()
        self._apply_memory_to_profile(db=db, user_id=user_id, memory=memory)
        db.commit()
        return self.get_profile_bundle(db=db, user_id=user_id)

    def reject_memory(self, *, db: Session, user_id: int, memory_id: int) -> UserProfileResponse:
        memory = self._get_memory_for_user(db=db, user_id=user_id, memory_id=memory_id)
        if memory.status != "pending":
            raise HTTPException(status_code=400, detail="只能拒绝待确认记忆")
        memory.status = "rejected"
        memory.updated_at = datetime.now()
        db.commit()
        return self.get_profile_bundle(db=db, user_id=user_id)

    def delete_memory(self, *, db: Session, user_id: int, memory_id: int) -> UserProfileResponse:
        memory = self._get_memory_for_user(db=db, user_id=user_id, memory_id=memory_id)
        if memory.status == "confirmed":
            self._remove_memory_from_profile(db=db, user_id=user_id, memory=memory)
        db.delete(memory)
        db.commit()
        return self.get_profile_bundle(db=db, user_id=user_id)

    def build_recommendation_context(self, *, db: Session, user_id: int) -> RecommendationContext:
        profile = self.get_or_create_profile(db=db, user_id=user_id)
        feedbacks = self._list_recipe_feedbacks(db=db, user_id=user_id, limit=80)
        recent_since = datetime.now() - timedelta(days=7)
        meals = db.execute(
            select(MealRecord)
            .where(MealRecord.user_id == user_id, MealRecord.recorded_at >= recent_since)
            .order_by(MealRecord.recorded_at.desc())
        ).scalars().all()
        disliked = normalize_tags([
            item.dish_name for item in feedbacks if item.feedback_type in {"dislike", "unavailable", "too_complex"}
        ])
        liked = normalize_tags([item.dish_name for item in feedbacks if item.feedback_type == "like"])
        return RecommendationContext(
            goal=profile.goal or "",
            allergies=_loads_list(profile.allergy_json),
            taboos=_loads_list(profile.taboo_json),
            preferences=_loads_list(profile.diet_preference_json),
            health_concerns=_loads_list(profile.health_concerns_json),
            disliked_dishes=disliked,
            liked_dishes=liked,
            recent_meals=[
                {
                    "recorded_at": meal.recorded_at.isoformat(),
                    "meal_type": meal.meal_type,
                    "calories": meal.estimated_calories_kcal,
                    "protein": meal.estimated_protein_g,
                    "carbohydrate": meal.estimated_carbohydrate_g,
                    "fat": meal.estimated_fat_g,
                    "foods_json": meal.foods_json,
                }
                for meal in meals
            ],
        )

    def create_recipe_feedback(
        self,
        *,
        db: Session,
        user_id: int,
        payload: RecipeFeedbackCreate,
    ) -> RecipeFeedbackResponse:
        row = RecipeFeedback(
            user_id=user_id,
            recipe_plan_id=payload.recipe_plan_id,
            dish_name=payload.dish_name.strip(),
            feedback_type=payload.feedback_type,
            comment=payload.comment.strip() if payload.comment else None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return RecipeFeedbackResponse.model_validate(row)

    def save_recipe_plan(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        plan_type: str,
        plan_content: dict,
        generation_basis: dict,
    ) -> RecipePlan:
        row = RecipePlan(
            user_id=user_id,
            source_session_id=session_id,
            plan_type=plan_type,
            plan_content_json=json.dumps(plan_content, ensure_ascii=False),
            generation_basis_json=json.dumps(generation_basis, ensure_ascii=False),
        )
        db.add(row)
        db.flush()
        return row

    def _profile_payload(self, profile: UserProfile) -> UserProfilePayload:
        return UserProfilePayload(
            age=profile.age,
            gender=profile.gender,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            goal=profile.goal or "",
            allergies=_loads_list(profile.allergy_json),
            taboos=_loads_list(profile.taboo_json),
            preferences=_loads_list(profile.diet_preference_json),
            health_concerns=_loads_list(profile.health_concerns_json),
            has_medical_report=bool(profile.medical_report_text),
            medical_report_text=profile.medical_report_text,
        )

    def _list_memories(self, *, db: Session, user_id: int, status: str) -> list[UserMemory]:
        return list(
            db.execute(
                select(UserMemory)
                .where(UserMemory.user_id == user_id, UserMemory.status == status)
                .order_by(UserMemory.created_at.desc(), UserMemory.id.desc())
            ).scalars()
        )

    def _list_recipe_plans(self, *, db: Session, user_id: int, limit: int = 10) -> list[RecipePlan]:
        return list(
            db.execute(
                select(RecipePlan)
                .where(RecipePlan.user_id == user_id)
                .order_by(RecipePlan.created_at.desc(), RecipePlan.id.desc())
                .limit(limit)
            ).scalars()
        )

    def _list_recipe_feedbacks(self, *, db: Session, user_id: int, limit: int = 50) -> list[RecipeFeedback]:
        return list(
            db.execute(
                select(RecipeFeedback)
                .where(RecipeFeedback.user_id == user_id)
                .order_by(RecipeFeedback.created_at.desc(), RecipeFeedback.id.desc())
                .limit(limit)
            ).scalars()
        )

    def _plan_response(self, row: RecipePlan) -> RecipePlanResponse:
        try:
            plan_content = json.loads(row.plan_content_json or "{}")
        except Exception:
            plan_content = {}
        try:
            generation_basis = json.loads(row.generation_basis_json or "{}")
        except Exception:
            generation_basis = {}
        return RecipePlanResponse(
            id=row.id,
            source_session_id=row.source_session_id,
            plan_type=row.plan_type,
            plan_content=plan_content if isinstance(plan_content, dict) else {"items": plan_content},
            generation_basis=generation_basis if isinstance(generation_basis, dict) else {},
            created_at=row.created_at,
        )

    def _get_memory_for_user(self, *, db: Session, user_id: int, memory_id: int) -> UserMemory:
        memory = db.execute(
            select(UserMemory).where(UserMemory.id == memory_id, UserMemory.user_id == user_id)
        ).scalar_one_or_none()
        if memory is None:
            raise HTTPException(status_code=404, detail="记忆不存在")
        return memory

    def _apply_memory_to_profile(self, *, db: Session, user_id: int, memory: UserMemory) -> None:
        profile = self.get_or_create_profile(db=db, user_id=user_id)
        if memory.memory_type == "goal":
            profile.goal = memory.content
            profile.updated_at = datetime.now()
            return
        field_map = {
            "allergy": "allergy_json",
            "taboo": "taboo_json",
            "preference": "diet_preference_json",
            "health_concern": "health_concerns_json",
        }
        field_name = field_map.get(memory.memory_type)
        if field_name is None:
            return
        values = _loads_list(getattr(profile, field_name))
        values = normalize_tags([*values, memory.content])
        setattr(profile, field_name, json.dumps(values, ensure_ascii=False))
        profile.updated_at = datetime.now()

    def _remove_memory_from_profile(self, *, db: Session, user_id: int, memory: UserMemory) -> None:
        profile = self.get_or_create_profile(db=db, user_id=user_id)
        if memory.memory_type == "goal":
            if profile.goal == memory.content:
                profile.goal = ""
                profile.updated_at = datetime.now()
            return
        field_map = {
            "allergy": "allergy_json",
            "taboo": "taboo_json",
            "preference": "diet_preference_json",
            "health_concern": "health_concerns_json",
        }
        field_name = field_map.get(memory.memory_type)
        if field_name is None:
            return
        values = [item for item in _loads_list(getattr(profile, field_name)) if item != memory.content]
        setattr(profile, field_name, json.dumps(values, ensure_ascii=False))
        profile.updated_at = datetime.now()


profile_service = CSideProfileService()
