from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from uuid import uuid4

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


def test_single_meal_image_analysis_is_saved_to_history(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path)
    token = register_and_login(client, "meal_image")
    session = client.post(
        "/api/chat/sessions",
        json={"title": "Image meal"},
        headers=auth_headers(token),
    ).json()

    monkeypatch.setattr(
        "app.services.chat_service.llm_service.analyze_single_meal_image",
        lambda **kwargs: (
            "## 单张餐食图片分析\n\n"
            "| 食物 | 估算克数 | 食物类别 |\n"
            "| --- | ---: | --- |\n"
            "| 清炒菜心 | 180 克 | 蔬菜 |\n\n"
            "- 热量：约 180 kcal\n"
            "- 蛋白质：约 5 g\n"
            "- 碳水：约 12 g\n"
            "- 脂肪：约 9 g\n"
        ),
    )

    response = client.post(
        f"/api/chat/sessions/{session['id']}/messages",
        data={"content": "这是我的午餐，帮我分析并记录。"},
        files={"file": ("meal.png", b"fake-image", "image/png")},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    history_response = client.get("/api/meals/records?days=7", headers=auth_headers(token))

    assert history_response.status_code == 200
    records = history_response.json()["records"]
    assert len(records) == 1
    assert records[0]["meal_type"] == "午餐"
    assert records[0]["foods"][0]["food_name"] == "清炒菜心"
    assert records[0]["foods"][0]["estimated_grams"] == 180
    assert records[0]["estimated_calories_kcal"] == 180


def test_streamed_single_meal_image_analysis_is_saved_to_history(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path)
    token = register_and_login(client, "meal_stream")
    session = client.post(
        "/api/chat/sessions",
        json={"title": "Stream image meal"},
        headers=auth_headers(token),
    ).json()

    monkeypatch.setattr(
        "app.services.chat_service.llm_service.analyze_single_meal_image",
        lambda **kwargs: (
            "## 单张餐食图片分析\n\n"
            "| 食物 | 判断依据 | 估算份量 | 估算克数 | 食物类别 |\n"
            "| --- | --- | ---: | ---: | --- |\n"
            "| 清炒菜心 | 绿色茎叶蔬菜 | 1 碗 | 约 180 克 | 蔬菜 |\n\n"
            "- 热量：约 180 kcal\n"
            "- 蛋白质：约 5 g\n"
            "- 碳水：约 12 g\n"
            "- 脂肪：约 9 g\n"
        ),
    )

    response = client.post(
        f"/api/chat/sessions/{session['id']}/messages/stream",
        data={"content": "这是我的午餐，帮我分析并记录。"},
        files={"file": ("meal.png", b"fake-image", "image/png")},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert '"type": "done"' in response.text

    history_response = client.get("/api/meals/records?days=7", headers=auth_headers(token))
    records = history_response.json()["records"]
    assert len(records) == 1
    assert records[0]["meal_type"] == "午餐"
    assert records[0]["foods"][0]["food_name"] == "清炒菜心"
    assert records[0]["foods"][0]["estimated_grams"] == 180


def test_meal_history_backfills_existing_single_image_analysis(tmp_path):
    client, session_factory = make_client(tmp_path)
    token = register_and_login(client, "meal_backfill")
    user_id = current_user_id(client, token)
    session = client.post(
        "/api/chat/sessions",
        json={"title": "Existing image meal"},
        headers=auth_headers(token),
    ).json()

    db = session_factory()
    try:
        db.add(
            ChatMessage(
                id=str(uuid4()),
                session_id=session["id"],
                user_id=user_id,
                role="user",
                content="这是我的午餐，帮我分析并记录。\n用户上传了图片文件：meal.png",
                thinking_content="",
                suggested_questions_json="[]",
            )
        )
        db.add(
            ChatMessage(
                id=str(uuid4()),
                session_id=session["id"],
                user_id=user_id,
                role="assistant",
                content=(
                    "## 单张餐食图片分析\n\n"
                    "| 食物 | 判断依据 | 估算份量 | 估算克数 | 食物类别 |\n"
                    "| --- | --- | ---: | ---: | --- |\n"
                    "| 清炒菜心 | 绿色茎叶蔬菜 | 1 碗 | 约 180 克 | 蔬菜 |\n\n"
                    "- 热量：约 180 kcal\n"
                    "- 蛋白质：约 5 g\n"
                    "- 碳水：约 12 g\n"
                    "- 脂肪：约 9 g\n"
                ),
                thinking_content="",
                suggested_questions_json="[]",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/meals/records?days=7", headers=auth_headers(token))

    assert response.status_code == 200
    records = response.json()["records"]
    assert len(records) == 1
    assert records[0]["session_id"] == session["id"]
    assert records[0]["foods"][0]["food_name"] == "清炒菜心"
    assert records[0]["estimated_calories_kcal"] == 180

    second_response = client.get("/api/meals/records?days=7", headers=auth_headers(token))
    assert len(second_response.json()["records"]) == 1


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


def test_delete_meal_record_hides_only_current_users_record(tmp_path):
    client, session_factory = make_client(tmp_path)
    alice = register_and_login(client, "meal_delete_alice")
    bob = register_and_login(client, "meal_delete_bob")
    alice_id = current_user_id(client, alice)
    bob_id = current_user_id(client, bob)
    alice_record_id = insert_meal(
        session_factory,
        user_id=alice_id,
        session_id="alice-delete-session",
        days_ago=0,
        meal_type="午餐",
        foods=[{"name": "清炒菜心"}],
        calories=550,
        protein=25,
        carbohydrate=15,
        fat=35,
    )
    keep_record_id = insert_meal(
        session_factory,
        user_id=alice_id,
        session_id="alice-keep-session",
        days_ago=0,
        meal_type="晚餐",
        foods=[{"name": "番茄炒蛋"}],
        calories=450,
        protein=20,
        carbohydrate=25,
        fat=20,
    )
    bob_record_id = insert_meal(
        session_factory,
        user_id=bob_id,
        session_id="bob-delete-session",
        days_ago=0,
        meal_type="午餐",
        foods=[{"name": "清蒸鱼"}],
        calories=420,
        protein=36,
        carbohydrate=30,
        fat=12,
    )

    delete_response = client.delete(
        f"/api/meals/records/{alice_record_id}?days=7",
        headers=auth_headers(alice),
    )

    assert delete_response.status_code == 200
    payload = delete_response.json()
    assert [item["id"] for item in payload["records"]] == [keep_record_id]
    assert payload["totals"]["calories_kcal"] == 450
    assert payload["daily_summaries"][0]["meal_count"] == 1

    cross_user_response = client.delete(
        f"/api/meals/records/{bob_record_id}?days=7",
        headers=auth_headers(alice),
    )
    assert cross_user_response.status_code == 404

    bob_history_response = client.get("/api/meals/records?days=7", headers=auth_headers(bob))
    assert [item["id"] for item in bob_history_response.json()["records"]] == [bob_record_id]

    alice_history_response = client.get("/api/meals/records?days=7", headers=auth_headers(alice))
    assert [item["id"] for item in alice_history_response.json()["records"]] == [keep_record_id]


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
