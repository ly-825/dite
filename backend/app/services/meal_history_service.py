from __future__ import annotations

from datetime import datetime, timedelta
import json
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.agents.workflow_agents import MealRecordAgent
from app.models.chat import ChatMessage
from app.models.meal_record import MealRecord
from app.models.user_profile import UserProfile
from app.schemas.chat import MealRecordData, WorkflowState
from app.schemas.meal_history import (
    DailyMealSummary,
    MealHistoryResponse,
    MealNutritionTotals,
    MealRecordResponse,
    MealReviewResponse,
)

DELETED_FEEDBACK_MARKER = "__deleted__"
MEAL_FEEDBACK_LIKED = "liked"
MEAL_FEEDBACK_DISLIKED = "disliked"
NON_FOOD_LABELS = {
    "热量",
    "能量",
    "卡路里",
    "总热量",
    "蛋白质",
    "碳水",
    "碳水化合物",
    "脂肪",
    "膳食纤维",
    "纤维",
    "钠",
    "糖",
    "营养素",
    "合计",
    "总计",
}


class MealHistoryService:
    def list_records(self, *, db: Session, user_id: int, days: int = 7) -> MealHistoryResponse:
        self._backfill_single_image_records_from_chat(db=db, user_id=user_id, days=days)
        records = self._load_recent_records(db=db, user_id=user_id, days=days)
        return self._build_history_response(records=records, days=days)

    def build_review(self, *, db: Session, user_id: int, days: int = 7) -> MealReviewResponse:
        self._backfill_single_image_records_from_chat(db=db, user_id=user_id, days=days)
        records = self._load_recent_records(db=db, user_id=user_id, days=days)
        goal = self._load_goal(db=db, user_id=user_id)
        return self._build_review_response(records=records, days=days, goal=goal)

    def delete_record(self, *, db: Session, user_id: int, record_id: int) -> bool:
        record = db.execute(
            select(MealRecord)
            .where(MealRecord.id == record_id, MealRecord.user_id == user_id)
            .where(or_(MealRecord.user_feedback.is_(None), MealRecord.user_feedback != DELETED_FEEDBACK_MARKER))
        ).scalar_one_or_none()
        if record is None:
            return False

        record.user_feedback = DELETED_FEEDBACK_MARKER
        db.commit()
        return True

    def update_record_feedback(
        self,
        *,
        db: Session,
        user_id: int,
        record_id: int,
        feedback: str | None,
    ) -> bool:
        record = db.execute(
            select(MealRecord)
            .where(MealRecord.id == record_id, MealRecord.user_id == user_id)
            .where(or_(MealRecord.user_feedback.is_(None), MealRecord.user_feedback != DELETED_FEEDBACK_MARKER))
        ).scalar_one_or_none()
        if record is None:
            return False

        record.user_feedback = feedback
        db.commit()
        return True

    def build_review_from_records(
        self,
        *,
        records: list[MealRecord],
        days: int = 7,
        goal: str = "",
    ) -> MealReviewResponse:
        return self._build_review_response(records=records, days=days, goal=goal)

    def extract_recent_foods(self, records: list[MealRecord], *, limit: int = 12) -> list[str]:
        foods: list[str] = []
        seen: set[str] = set()
        for record in records:
            for item in self._loads_foods(record.foods_json):
                name = self._food_name(item)
                if not name or name in seen:
                    continue
                seen.add(name)
                foods.append(name)
                if len(foods) >= limit:
                    return foods
        return foods

    def extract_feedback_foods(self, records: list[MealRecord], feedback: str, *, limit: int = 20) -> list[str]:
        foods: list[str] = []
        seen: set[str] = set()
        for record in records:
            if record.user_feedback != feedback:
                continue
            for item in self._loads_foods(record.foods_json):
                name = self._food_name(item)
                if not name or name in seen:
                    continue
                seen.add(name)
                foods.append(name)
                if len(foods) >= limit:
                    return foods
        return foods

    def _load_recent_records(self, *, db: Session, user_id: int, days: int) -> list[MealRecord]:
        safe_days = max(1, min(days, 90))
        since = datetime.now() - timedelta(days=safe_days)
        return list(
            db.execute(
                select(MealRecord)
                .where(MealRecord.user_id == user_id, MealRecord.recorded_at >= since)
                .where(or_(MealRecord.user_feedback.is_(None), MealRecord.user_feedback != DELETED_FEEDBACK_MARKER))
                .order_by(MealRecord.recorded_at.desc(), MealRecord.id.desc())
            ).scalars().all()
        )

    def _load_goal(self, *, db: Session, user_id: int) -> str:
        profile = db.execute(select(UserProfile).where(UserProfile.user_id == user_id)).scalar_one_or_none()
        return (profile.goal or "").strip() if profile else ""

    def _backfill_single_image_records_from_chat(self, *, db: Session, user_id: int, days: int) -> None:
        safe_days = max(1, min(days, 90))
        since = datetime.now() - timedelta(days=safe_days)
        existing_keys = {
            (session_id, (analysis_markdown or "").strip())
            for session_id, analysis_markdown in db.execute(
                select(MealRecord.session_id, MealRecord.analysis_markdown)
                .where(MealRecord.user_id == user_id, MealRecord.recorded_at >= since)
            ).all()
        }
        messages = list(
            db.execute(
                select(ChatMessage)
                .where(ChatMessage.user_id == user_id, ChatMessage.created_at >= since)
                .where(ChatMessage.role.in_(["user", "assistant"]))
                .order_by(ChatMessage.session_id, ChatMessage.created_at, ChatMessage.id)
            ).scalars().all()
        )
        if not messages:
            return

        agent = MealRecordAgent()
        state = WorkflowState()
        last_user_message_by_session: dict[str, str] = {}
        created = False
        for message in messages:
            if message.role == "user":
                last_user_message_by_session[message.session_id] = message.content
                continue
            if "单张餐食图片分析" not in message.content:
                continue
            key = (message.session_id, message.content.strip())
            if key in existing_keys:
                continue
            record = agent.record_single_image_analysis(
                state,
                user_message=last_user_message_by_session.get(message.session_id, ""),
                analysis_markdown=message.content,
                recorded_at=message.created_at,
            )
            if record is None:
                continue
            self._add_meal_record_row(
                db=db,
                user_id=user_id,
                session_id=message.session_id,
                record=record,
            )
            existing_keys.add(key)
            created = True
        if created:
            db.commit()

    def _add_meal_record_row(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        record: MealRecordData,
    ) -> None:
        db.add(
            MealRecord(
                user_id=user_id,
                session_id=session_id,
                recorded_at=record.recorded_at,
                meal_type=record.meal_type,
                foods_json=json.dumps(
                    [food.model_dump(mode="json") for food in record.consumed_items],
                    ensure_ascii=False,
                ),
                estimated_calories_kcal=record.estimated_calories_kcal,
                estimated_protein_g=record.estimated_protein_g,
                estimated_carbohydrate_g=record.estimated_carbohydrate_g,
                estimated_fat_g=record.estimated_fat_g,
                analysis_markdown=record.analysis_markdown or "",
            )
        )

    def _build_history_response(self, *, records: list[MealRecord], days: int) -> MealHistoryResponse:
        daily = self._daily_summaries(records)
        return MealHistoryResponse(
            days=days,
            records=[self._record_response(record) for record in records],
            daily_summaries=daily,
            totals=self._totals(records),
            recent_foods=self.extract_recent_foods(records),
        )

    def _build_review_response(self, *, records: list[MealRecord], days: int, goal: str) -> MealReviewResponse:
        totals = self._totals(records)
        daily = self._daily_summaries(records)
        divisor = max(len(daily), 1)
        avg_calories = round(totals.calories_kcal / divisor)
        avg_protein = round(totals.protein_g / divisor, 1)
        avg_carbohydrate = round(totals.carbohydrate_g / divisor, 1)
        avg_fat = round(totals.fat_g / divisor, 1)
        calorie_target = self._calorie_target(goal)
        protein_target = self._protein_target(goal)
        problems: list[str] = []
        suggestions: list[str] = []

        if records and avg_calories > calorie_target * 1.1:
            problems.append(f"最近有记录日的平均热量约 {avg_calories} kcal，高于当前目标参考值。")
            suggestions.append("下一餐优先控制主食和高脂菜分量，晚餐尽量选择清淡蛋白和蔬菜组合。")
        if records and avg_protein < protein_target:
            problems.append(f"最近有记录日的平均蛋白质约 {avg_protein:g} g，低于建议参考值。")
            suggestions.append("下一餐增加鸡蛋、鱼肉、鸡胸肉、豆制品或奶类等优质蛋白。")
        if not records:
            suggestions.append("先上传几次餐前餐后图片，系统会根据真实摄入生成趋势复盘。")
        if records and not problems:
            suggestions.append("最近记录整体没有明显异常，下一餐继续保持主食、蛋白质和蔬菜的均衡搭配。")

        return MealReviewResponse(
            days=days,
            record_count=len(records),
            days_with_records=len(daily),
            totals=totals,
            average_daily_calories_kcal=avg_calories,
            average_daily_protein_g=avg_protein,
            average_daily_carbohydrate_g=avg_carbohydrate,
            average_daily_fat_g=avg_fat,
            recent_foods=self.extract_recent_foods(records),
            problems=problems,
            suggestions=suggestions,
        )

    def _record_response(self, record: MealRecord) -> MealRecordResponse:
        return MealRecordResponse(
            id=record.id,
            session_id=record.session_id,
            recorded_at=record.recorded_at,
            meal_type=record.meal_type,
            foods=self._loads_foods(record.foods_json),
            estimated_calories_kcal=record.estimated_calories_kcal,
            estimated_protein_g=record.estimated_protein_g,
            estimated_carbohydrate_g=record.estimated_carbohydrate_g,
            estimated_fat_g=record.estimated_fat_g,
            user_feedback=record.user_feedback,
            analysis_markdown=record.analysis_markdown,
        )

    def _daily_summaries(self, records: list[MealRecord]) -> list[DailyMealSummary]:
        buckets: dict[str, dict[str, float | int]] = {}
        for record in records:
            key = record.recorded_at.date().isoformat()
            bucket = buckets.setdefault(
                key,
                {"meal_count": 0, "calories": 0, "protein": 0.0, "carbohydrate": 0.0, "fat": 0.0},
            )
            bucket["meal_count"] = int(bucket["meal_count"]) + 1
            bucket["calories"] = int(bucket["calories"]) + int(record.estimated_calories_kcal or 0)
            bucket["protein"] = float(bucket["protein"]) + float(record.estimated_protein_g or 0)
            bucket["carbohydrate"] = float(bucket["carbohydrate"]) + float(record.estimated_carbohydrate_g or 0)
            bucket["fat"] = float(bucket["fat"]) + float(record.estimated_fat_g or 0)
        return [
            DailyMealSummary(
                date=date,
                meal_count=int(values["meal_count"]),
                calories_kcal=int(values["calories"]),
                protein_g=round(float(values["protein"]), 1),
                carbohydrate_g=round(float(values["carbohydrate"]), 1),
                fat_g=round(float(values["fat"]), 1),
            )
            for date, values in sorted(buckets.items(), reverse=True)
        ]

    def _totals(self, records: list[MealRecord]) -> MealNutritionTotals:
        return MealNutritionTotals(
            calories_kcal=sum(int(record.estimated_calories_kcal or 0) for record in records),
            protein_g=round(sum(float(record.estimated_protein_g or 0) for record in records), 1),
            carbohydrate_g=round(sum(float(record.estimated_carbohydrate_g or 0) for record in records), 1),
            fat_g=round(sum(float(record.estimated_fat_g or 0) for record in records), 1),
        )

    def _loads_foods(self, payload: str | None) -> list[dict[str, Any]]:
        if not payload:
            return []
        try:
            value = json.loads(payload)
        except Exception:
            return []
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict) and self._food_name(item)]

    def _food_name(self, item: dict[str, Any]) -> str:
        for key in ["name", "food_name", "dish_name", "食物", "菜品"]:
            value = str(item.get(key) or "").strip()
            if value and self._is_food_name_candidate(value):
                return value
        return ""

    def _is_food_name_candidate(self, value: str) -> bool:
        name = value.strip(" *：:")
        if not name:
            return False
        return name not in NON_FOOD_LABELS

    def _calorie_target(self, goal: str) -> int:
        if "减脂" in goal:
            return 1700
        if "增肌" in goal:
            return 2300
        return 1900

    def _protein_target(self, goal: str) -> int:
        if "增肌" in goal:
            return 90
        return 70


meal_history_service = MealHistoryService()
