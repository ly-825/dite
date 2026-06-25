from pathlib import Path

import pytest
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


@pytest.fixture(autouse=True)
def disable_real_llm_memory_extraction(monkeypatch):
    monkeypatch.setattr("app.services.llm_service.llm_service.enabled", False)
    monkeypatch.setattr("app.services.llm_service.llm_service.client", None)
    monkeypatch.setattr(
        "app.services.profile_service.llm_service.extract_user_memory_candidates",
        lambda *, user_message: None,
    )


def make_client(tmp_path: Path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    chat_service.reset_runtime_state_for_tests(bodyreport_dir=tmp_path / "bodyreport")
    return TestClient(app)


def register_and_login(client: TestClient, username: str) -> str:
    password = "StrongPass123"
    response = client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    assert response.status_code == 201
    login_response = client.post("/api/auth/login", json={"account": username, "password": password})
    assert login_response.status_code == 200
    return login_response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_profile_requires_login(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/profile")

    assert response.status_code == 401


def test_profile_is_scoped_to_current_user_and_normalizes_tags(tmp_path):
    client = make_client(tmp_path)
    alice = register_and_login(client, "c_alice")
    bob = register_and_login(client, "c_bob")

    update_response = client.put(
        "/api/profile",
        headers=auth_headers(alice),
        json={
            "age": 29,
            "gender": "female",
            "height_cm": 168,
            "weight_kg": 58,
            "goal": "减脂",
            "allergies": ["花生", "花生", "  海鲜  "],
            "taboos": ["香菜", ""],
            "preferences": ["清淡", "少油", "清淡"],
            "health_concerns": ["血糖偏高"],
        },
    )

    assert update_response.status_code == 200
    alice_profile = update_response.json()["profile"]
    assert alice_profile["goal"] == "减脂"
    assert alice_profile["allergies"] == ["花生", "海鲜"]
    assert alice_profile["taboos"] == ["香菜"]
    assert alice_profile["preferences"] == ["清淡", "少油"]

    bob_response = client.get("/api/profile", headers=auth_headers(bob))
    assert bob_response.status_code == 200
    assert bob_response.json()["profile"]["goal"] == ""
    assert bob_response.json()["profile"]["allergies"] == []


def test_chat_auto_confirms_memory_and_mentions_saved_items(tmp_path):
    client = make_client(tmp_path)
    token = register_and_login(client, "memory_user")
    session = client.post(
        "/api/chat/sessions",
        json={"title": "Memory"},
        headers=auth_headers(token),
    ).json()

    response = client.post(
        f"/api/chat/sessions/{session['id']}/messages",
        json={"content": "我不吃香菜，也对花生过敏。"},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    assistant_reply = response.json()["messages"][-1]["content"]
    assert assistant_reply.startswith("已记住")
    assert "已记住" in assistant_reply
    assert "香菜" in assistant_reply
    assert "花生" in assistant_reply
    assert "食谱建议" not in assistant_reply
    assert "早餐" not in assistant_reply
    assert "午餐" not in assistant_reply

    profile = client.get("/api/profile", headers=auth_headers(token)).json()
    confirmed = profile["confirmed_memories"]
    confirmed_pairs = [{"memory_type": item["memory_type"], "content": item["content"]} for item in confirmed]
    assert profile["pending_memories"] == []
    assert {"memory_type": "taboo", "content": "香菜"} in confirmed_pairs
    assert {"memory_type": "allergy", "content": "花生"} in confirmed_pairs
    assert "香菜" in profile["profile"]["taboos"]
    assert "花生" in profile["profile"]["allergies"]

    taboo_memory = next(item for item in confirmed if item["memory_type"] == "taboo")
    delete = client.delete(
        f"/api/profile/memories/{taboo_memory['id']}",
        headers=auth_headers(token),
    )
    assert delete.status_code == 200
    assert "香菜" not in delete.json()["profile"]["taboos"]


def test_duplicate_auto_confirmed_memory_is_not_saved_twice(tmp_path):
    client = make_client(tmp_path)
    token = register_and_login(client, "dedupe_memory")
    session = client.post("/api/chat/sessions", json={"title": "Dedupe"}, headers=auth_headers(token)).json()

    for _ in range(2):
        client.post(
            f"/api/chat/sessions/{session['id']}/messages",
            json={"content": "我喜欢红烧肉。"},
            headers=auth_headers(token),
        )

    profile = client.get("/api/profile", headers=auth_headers(token)).json()
    confirmed = [
        item for item in profile["confirmed_memories"]
        if item["memory_type"] == "preference" and item["content"] == "红烧肉"
    ]
    assert len(confirmed) == 1
    assert profile["profile"]["preferences"] == ["红烧肉"]


def test_llm_memory_extractor_auto_confirms_natural_language_taboos(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    token = register_and_login(client, "llm_memory")
    session = client.post("/api/chat/sessions", json={"title": "LLM Memory"}, headers=auth_headers(token)).json()

    def fake_extract_user_memory_candidates(*, user_message: str):
        assert user_message == "我不喜欢吃葱，不吃香菜。"
        return [
            {"type": "taboo", "content": "葱"},
            {"type": "taboo", "content": "香菜"},
        ]

    monkeypatch.setattr(
        "app.services.profile_service.llm_service.extract_user_memory_candidates",
        fake_extract_user_memory_candidates,
    )

    response = client.post(
        f"/api/chat/sessions/{session['id']}/messages",
        json={"content": "我不喜欢吃葱，不吃香菜。"},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assistant_reply = response.json()["messages"][-1]["content"]
    assert assistant_reply.startswith("已记住")
    assert "葱" in assistant_reply
    assert "香菜" in assistant_reply
    assert "食谱建议" not in assistant_reply

    profile = client.get("/api/profile", headers=auth_headers(token)).json()
    assert profile["profile"]["taboos"] == ["葱", "香菜"]


def test_repeated_memory_only_message_does_not_generate_recipe(tmp_path):
    client = make_client(tmp_path)
    token = register_and_login(client, "repeat_memory")
    session = client.post("/api/chat/sessions", json={"title": "Repeat"}, headers=auth_headers(token)).json()

    for _ in range(2):
        response = client.post(
            f"/api/chat/sessions/{session['id']}/messages",
            json={"content": "我不吃香菜，也对花生过敏。"},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assistant_reply = response.json()["messages"][-1]["content"]
        assert assistant_reply.startswith("已记住")
        assert "食谱建议" not in assistant_reply
        assert "早餐" not in assistant_reply


def test_memory_message_with_explicit_recipe_request_still_generates_recipe(tmp_path):
    client = make_client(tmp_path)
    token = register_and_login(client, "memory_recipe")
    session = client.post("/api/chat/sessions", json={"title": "Memory Recipe"}, headers=auth_headers(token)).json()

    response = client.post(
        f"/api/chat/sessions/{session['id']}/messages",
        json={"content": "我不吃香菜，帮我做一份减脂食谱。"},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assistant_reply = response.json()["messages"][-1]["content"]
    assert "食谱建议" in assistant_reply
    assert "已记住" in assistant_reply
    assert "香菜" in client.get("/api/profile", headers=auth_headers(token)).json()["profile"]["taboos"]


def test_recipe_feedback_and_context_are_scoped_to_user(tmp_path):
    client = make_client(tmp_path)
    alice = register_and_login(client, "recipe_alice")
    bob = register_and_login(client, "recipe_bob")

    feedback_response = client.post(
        "/api/profile/recipe-feedbacks",
        headers=auth_headers(alice),
        json={"dish_name": "红烧肉", "feedback_type": "dislike", "comment": "太油"},
    )
    assert feedback_response.status_code == 201

    alice_profile = client.get("/api/profile", headers=auth_headers(alice)).json()
    bob_profile = client.get("/api/profile", headers=auth_headers(bob)).json()
    assert alice_profile["recipe_feedbacks"][0]["dish_name"] == "红烧肉"
    assert bob_profile["recipe_feedbacks"] == []


def test_confirmed_profile_context_loads_into_new_chat_session(tmp_path):
    client = make_client(tmp_path)
    token = register_and_login(client, "context_user")
    client.put(
        "/api/profile",
        headers=auth_headers(token),
        json={
            "goal": "控糖",
            "allergies": ["海鲜"],
            "taboos": ["香菜"],
            "preferences": ["清淡"],
            "health_concerns": ["血糖偏高"],
        },
    )

    session = client.post("/api/chat/sessions", json={"title": "Context"}, headers=auth_headers(token))

    assert session.status_code == 200
    state = session.json()["workflow_state"]
    assert state["goal"] == "控糖"
    assert "海鲜" in state["allergy"]
    assert "香菜" in state["diet_preference"]
    assert "血糖偏高" in state["disease"]
