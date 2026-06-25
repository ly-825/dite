from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (  # noqa: F401
    ChatMessage,
    ChatSession,
    MealRecord,
    RecipeFeedback,
    RecipePlan,
    User,
    UserMemory,
    UserProfile,
)
from app.services.chat_service import chat_service
from app.services.profile_service import profile_service


def make_client(tmp_path: Path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    chat_service.reset_runtime_state_for_tests(bodyreport_dir=tmp_path / "bodyreport")
    return TestClient(app), testing_session_local


def register_and_login(client: TestClient, username: str) -> str:
    password = "StrongPass123"
    response = client.post("/api/auth/register", json={"username": username, "password": password})
    assert response.status_code == 201
    login_response = client.post("/api/auth/login", json={"account": username, "password": password})
    assert login_response.status_code == 200
    return login_response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def insert_meal(
    session_factory,
    *,
    user_id: int,
    session_id: str,
    days_ago: int,
    meal_type: str,
    foods: list[dict],
    calories: int,
    protein: float,
    carbohydrate: float,
    fat: float,
):
    db = session_factory()
    try:
        row = MealRecord(
            user_id=user_id,
            session_id=session_id,
            recorded_at=datetime.now() - timedelta(days=days_ago),
            meal_type=meal_type,
            foods_json=json.dumps(foods, ensure_ascii=False),
            estimated_calories_kcal=calories,
            estimated_protein_g=protein,
            estimated_carbohydrate_g=carbohydrate,
            estimated_fat_g=fat,
            analysis_markdown=f"{meal_type} 分析",
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def current_user_id(client: TestClient, token: str) -> int:
    return client.get("/api/auth/me", headers=auth_headers(token)).json()["id"]


def test_meal_records_require_login(tmp_path):
    client, _ = make_client(tmp_path)

    response = client.get("/api/meals/records")

    assert response.status_code == 401


def test_meal_history_is_scoped_to_current_user_and_summarized(tmp_path):
    client, session_factory = make_client(tmp_path)
    alice = register_and_login(client, "meal_alice")
    bob = register_and_login(client, "meal_bob")
    alice_id = current_user_id(client, alice)
    bob_id = current_user_id(client, bob)
    insert_meal(
        session_factory,
        user_id=alice_id,
        session_id="alice-session",
        days_ago=1,
        meal_type="午餐",
        foods=[{"name": "红烧肉"}, {"name": "米饭"}],
        calories=900,
        protein=28,
        carbohydrate=95,
        fat=35,
    )
    insert_meal(
        session_factory,
        user_id=bob_id,
        session_id="bob-session",
        days_ago=1,
        meal_type="晚餐",
        foods=[{"name": "清蒸鱼"}],
        calories=420,
        protein=36,
        carbohydrate=30,
        fat=12,
    )

    response = client.get("/api/meals/records?days=7", headers=auth_headers(alice))

    assert response.status_code == 200
    payload = response.json()
    assert [item["meal_type"] for item in payload["records"]] == ["午餐"]
    assert payload["totals"]["calories_kcal"] == 900
    assert payload["totals"]["protein_g"] == 28
    assert payload["daily_summaries"][0]["calories_kcal"] == 900
    assert payload["daily_summaries"][0]["meal_count"] == 1
    assert payload["recent_foods"] == ["红烧肉", "米饭"]


def test_meal_review_flags_high_calories_and_low_protein(tmp_path):
    client, session_factory = make_client(tmp_path)
    token = register_and_login(client, "meal_review")
    user_id = current_user_id(client, token)
    client.put(
        "/api/profile",
        headers=auth_headers(token),
        json={"goal": "减脂", "allergies": [], "taboos": [], "preferences": [], "health_concerns": []},
    )
    insert_meal(
        session_factory,
        user_id=user_id,
        session_id="review-session",
        days_ago=1,
        meal_type="午餐",
        foods=[{"food_name": "红烧肉"}, {"food_name": "米饭"}],
        calories=980,
        protein=22,
        carbohydrate=100,
        fat=40,
    )
    insert_meal(
        session_factory,
        user_id=user_id,
        session_id="review-session",
        days_ago=1,
        meal_type="晚餐",
        foods=[{"food_name": "炒面"}],
        calories=940,
        protein=20,
        carbohydrate=120,
        fat=30,
    )

    response = client.get("/api/meals/review?days=7", headers=auth_headers(token))

    assert response.status_code == 200
    review = response.json()
    assert review["record_count"] == 2
    assert review["average_daily_calories_kcal"] == 1920
    assert review["average_daily_protein_g"] == 42
    assert any("热量" in item for item in review["problems"])
    assert any("蛋白质" in item for item in review["problems"])
    assert any("晚餐" in item or "下一餐" in item for item in review["suggestions"])


def test_recommendation_context_includes_recent_meal_review(tmp_path):
    client, session_factory = make_client(tmp_path)
    token = register_and_login(client, "meal_context")
    user_id = current_user_id(client, token)
    insert_meal(
        session_factory,
        user_id=user_id,
        session_id="context-session",
        days_ago=1,
        meal_type="午餐",
        foods=[{"name": "红烧肉"}],
        calories=920,
        protein=24,
        carbohydrate=95,
        fat=38,
    )

    db = session_factory()
    try:
        context = profile_service.build_recommendation_context(db=db, user_id=user_id)
    finally:
        db.close()

    dumped = context.model_dump()
    assert dumped["recent_meal_review"]["record_count"] == 1
    assert dumped["recent_meal_review"]["average_daily_calories_kcal"] == 920
    assert "红烧肉" in dumped["recent_foods"]
    assert any("蛋白质" in item for item in dumped["adjustment_hints"])
