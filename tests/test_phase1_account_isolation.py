from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.core.config import Settings
from app.main import app
from app.models import ChatMessage, ChatSession, MealRecord, User, UserProfile  # noqa: F401
from app.services.chat_service import chat_service


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

    client = TestClient(app)
    return client


def register_and_login(client: TestClient, username: str) -> str:
    email = f"{username}@example.com"
    password = "StrongPass123"
    register_response = client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/api/auth/login",
        json={"account": username, "password": password},
    )
    assert login_response.status_code == 200
    return login_response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_database_url_can_be_overridden_for_local_dev():
    settings = Settings(database_url_override="sqlite:///./local-dev.db")

    assert settings.database_url == "sqlite:///./local-dev.db"


def test_register_can_omit_email_and_login_with_username(tmp_path):
    client = make_client(tmp_path)

    register_response = client.post(
        "/api/auth/register",
        json={"username": "noemail_user", "password": "StrongPass123"},
    )

    assert register_response.status_code == 201
    registered = register_response.json()
    assert registered["username"] == "noemail_user"
    assert registered["email"] == "noemail_user@users.diet-delushan.com"

    login_response = client.post(
        "/api/auth/login",
        json={"account": "noemail_user", "password": "StrongPass123"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["user"]["username"] == "noemail_user"


def test_register_without_email_still_rejects_duplicate_username(tmp_path):
    client = make_client(tmp_path)

    first = client.post(
        "/api/auth/register",
        json={"username": "same_name", "password": "StrongPass123"},
    )
    second = client.post(
        "/api/auth/register",
        json={"username": "same_name", "password": "StrongPass123"},
    )

    assert first.status_code == 201
    assert second.status_code == 400
    assert second.json()["detail"] == "用户名已存在"


def test_register_with_email_keeps_existing_compatibility(tmp_path):
    client = make_client(tmp_path)

    register_response = client.post(
        "/api/auth/register",
        json={"username": "email_user", "email": "email_user@example.com", "password": "StrongPass123"},
    )

    assert register_response.status_code == 201
    assert register_response.json()["email"] == "email_user@example.com"


def test_chat_sessions_require_login(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/chat/sessions")

    assert response.status_code == 401


def test_chat_sessions_are_scoped_to_current_user(tmp_path):
    client = make_client(tmp_path)
    alice_token = register_and_login(client, "alice")
    bob_token = register_and_login(client, "bob")

    alice_session = client.post(
        "/api/chat/sessions",
        json={"title": "Alice plan"},
        headers=auth_headers(alice_token),
    )
    bob_session = client.post(
        "/api/chat/sessions",
        json={"title": "Bob plan"},
        headers=auth_headers(bob_token),
    )

    assert alice_session.status_code == 200
    assert bob_session.status_code == 200

    alice_sessions = client.get("/api/chat/sessions", headers=auth_headers(alice_token))
    bob_sessions = client.get("/api/chat/sessions", headers=auth_headers(bob_token))

    assert [item["title"] for item in alice_sessions.json()] == ["Alice plan"]
    assert [item["title"] for item in bob_sessions.json()] == ["Bob plan"]


def test_medical_report_is_not_shared_between_users(tmp_path):
    client = make_client(tmp_path)
    alice_token = register_and_login(client, "alice_report")
    bob_token = register_and_login(client, "bob_report")

    alice_session = client.post(
        "/api/chat/sessions",
        json={"title": "Alice report"},
        headers=auth_headers(alice_token),
    ).json()
    upload_response = client.post(
        f"/api/chat/sessions/{alice_session['id']}/medical-report",
        data={"report_text": "血糖偏高，低密度脂蛋白偏高。"},
        headers=auth_headers(alice_token),
    )
    assert upload_response.status_code == 200
    assert upload_response.json()["workflow_state"]["has_medical_report"] is True

    bob_session = client.post(
        "/api/chat/sessions",
        json={"title": "Bob clean"},
        headers=auth_headers(bob_token),
    )

    assert bob_session.status_code == 200
    assert bob_session.json()["workflow_state"]["has_medical_report"] is False
