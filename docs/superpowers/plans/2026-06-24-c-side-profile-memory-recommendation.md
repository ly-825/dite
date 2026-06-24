# C-Side Profile Memory Recommendation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the C-side personalization loop: editable profile, confirmable long-term memories, saved recipe plans, recipe feedback, and recommendation context injection.

**Architecture:** Add a focused `profile_service.py` and `profile.py` API router so profile and memory behavior does not bloat `chat_service.py`. Keep chat as the orchestration boundary, but delegate C-side profile, memory, recipe-plan, and feedback persistence to the profile service. Frontend adds a signed-in `/profile` page and lightweight C-side navigation while preserving the existing chat workspace.

**Tech Stack:** FastAPI, SQLAlchemy 2, Pydantic v2, MySQL/PyMySQL, SQLite test DB, Vue 3, Pinia, Vue Router, Vite.

## Global Constraints

- All C-side data must be scoped by authenticated `user_id`.
- Extracted chat memories must start as `pending`; only explicit user confirmation updates profile fields.
- Do not implement B-side canteen/menu/admin features in this phase.
- Do not add mobile phone registration in this phase.
- Keep `chat_service.py` orchestration-only for new C-side logic; put reusable profile and memory behavior in `backend/app/services/profile_service.py`.
- Preserve the existing SSE contract used by `frontend/src/utils/streamRequest.js`.
- Use TDD for backend behavior before production changes.

---

## File Structure

- Create `tests/test_c_side_profile_memory_recommendation.py`: backend tests for profile isolation, memory confirmation, recommendation context, recipe plans, and feedback.
- Modify `backend/app/models/user_profile.py`: add nullable C-side basic profile fields and `diet_preference_json`.
- Create `backend/app/models/user_memory.py`: extracted memory rows.
- Create `backend/app/models/recipe_plan.py`: saved recipe plan rows.
- Create `backend/app/models/recipe_feedback.py`: dish feedback rows.
- Modify `backend/app/models/__init__.py`: export new models.
- Create `backend/app/schemas/profile.py`: API request and response models.
- Create `backend/app/services/profile_service.py`: profile bundle, memory extraction/confirmation, recommendation context, plan saving, feedback persistence.
- Create `backend/app/api/profile.py`: authenticated profile and feedback endpoints.
- Modify `backend/app/main.py`: include profile router.
- Modify `backend/app/services/chat_service.py`: call profile service after user messages, before agent execution, and after recipe replies.
- Modify `backend/app/schemas/chat.py`: add `recommendation_context` to `WorkflowState` for generation basis and saved plan metadata.
- Modify `backend/app/agents/workflow_agents.py`: make rule recipe fallback consider taboo/allergy/negative feedback context.
- Modify `sql/init.sql`: add fresh-install SQL for new fields and tables.
- Create `frontend/src/api/profile.js`: profile API calls.
- Create `frontend/src/stores/profile.js`: Pinia store for profile page.
- Create `frontend/src/views/ProfileView.vue`: C-side profile and memory UI.
- Modify `frontend/src/router/index.js`: add `/profile` signed-in route.
- Modify `frontend/src/views/HomeView.vue`: add navigation entry to profile page and clarify disabled C-side items.

---

### Task 1: Backend C-Side Behavior Tests

**Files:**
- Create: `tests/test_c_side_profile_memory_recommendation.py`

**Interfaces:**
- Consumes: `app.main.app`, `app.db.session.get_db`, `app.db.base.Base`, auth endpoints.
- Produces: failing tests that define C-side profile, memory, recipe plan, and feedback behavior.

- [ ] **Step 1: Create test helpers and auth setup**

Add this file with shared helpers:

```python
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
```

- [ ] **Step 2: Add profile auth and isolation tests**

Append:

```python
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
```

- [ ] **Step 3: Add memory extraction and confirmation tests**

Append:

```python
def test_chat_extracts_pending_memory_and_confirmation_updates_profile(tmp_path):
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

    profile = client.get("/api/profile", headers=auth_headers(token)).json()
    pending = profile["pending_memories"]
    assert {"memory_type": "taboo", "content": "香菜"} in [
        {"memory_type": item["memory_type"], "content": item["content"]} for item in pending
    ]
    assert {"memory_type": "allergy", "content": "花生"} in [
        {"memory_type": item["memory_type"], "content": item["content"]} for item in pending
    ]

    taboo_memory = next(item for item in pending if item["memory_type"] == "taboo")
    confirm = client.post(
        f"/api/profile/memories/{taboo_memory['id']}/confirm",
        headers=auth_headers(token),
    )
    assert confirm.status_code == 200
    assert "香菜" in confirm.json()["profile"]["taboos"]


def test_rejected_memory_does_not_update_profile(tmp_path):
    client = make_client(tmp_path)
    token = register_and_login(client, "reject_memory")
    session = client.post("/api/chat/sessions", json={"title": "Reject"}, headers=auth_headers(token)).json()

    client.post(
        f"/api/chat/sessions/{session['id']}/messages",
        json={"content": "我喜欢红烧肉。"},
        headers=auth_headers(token),
    )
    profile = client.get("/api/profile", headers=auth_headers(token)).json()
    memory = next(item for item in profile["pending_memories"] if item["memory_type"] == "preference")

    reject = client.post(f"/api/profile/memories/{memory['id']}/reject", headers=auth_headers(token))

    assert reject.status_code == 200
    assert "红烧肉" not in reject.json()["profile"]["preferences"]
```

- [ ] **Step 4: Add recipe context, plan, and feedback tests**

Append:

```python
def test_recipe_feedback_and_context_are_scoped_to_user(tmp_path):
    client = make_client(tmp_path)
    alice = register_and_login(client, "recipe_alice")
    bob = register_and_login(client, "recipe_bob")

    plan_response = client.post(
        "/api/profile/recipe-feedbacks",
        headers=auth_headers(alice),
        json={"dish_name": "红烧肉", "feedback_type": "dislike", "comment": "太油"},
    )
    assert plan_response.status_code == 201

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
```

- [ ] **Step 5: Run tests and verify RED**

Run:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest tests/test_c_side_profile_memory_recommendation.py -q
```

Expected: fail during import because `RecipeFeedback`, `RecipePlan`, `UserMemory`, or `/api/profile` does not exist yet.

---

### Task 2: Models And Schemas

**Files:**
- Modify: `backend/app/models/user_profile.py`
- Create: `backend/app/models/user_memory.py`
- Create: `backend/app/models/recipe_plan.py`
- Create: `backend/app/models/recipe_feedback.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/schemas/profile.py`

**Interfaces:**
- Consumes: `app.db.base.Base`, existing `users` table.
- Produces: importable SQLAlchemy models and Pydantic schemas used by profile service and API.

- [ ] **Step 1: Extend `UserProfile`**

Add fields to `backend/app/models/user_profile.py`:

```python
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
```

Inside `UserProfile`:

```python
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    diet_preference_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
```

- [ ] **Step 2: Create memory model**

Create `backend/app/models/user_memory.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserMemory(Base):
    """Confirmable long-term C-side memory."""

    __tablename__ = "user_memories"
    __table_args__ = (
        Index("idx_user_memories_user_status", "user_id", "status"),
        Index("idx_user_memories_dedupe", "user_id", "memory_type", "content", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="chat")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    source_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
```

- [ ] **Step 3: Create recipe plan model**

Create `backend/app/models/recipe_plan.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecipePlan(Base):
    """Saved generated C-side recipe plan."""

    __tablename__ = "recipe_plans"
    __table_args__ = (Index("idx_recipe_plans_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    source_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    plan_type: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    plan_content_json: Mapped[str] = mapped_column(Text, nullable=False)
    generation_basis_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
```

- [ ] **Step 4: Create recipe feedback model**

Create `backend/app/models/recipe_feedback.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecipeFeedback(Base):
    """Dish-level feedback that affects future recommendations."""

    __tablename__ = "recipe_feedbacks"
    __table_args__ = (
        Index("idx_recipe_feedbacks_user_dish", "user_id", "dish_name"),
        Index("idx_recipe_feedbacks_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    recipe_plan_id: Mapped[int | None] = mapped_column(ForeignKey("recipe_plans.id"), nullable=True, index=True)
    dish_name: Mapped[str] = mapped_column(String(120), nullable=False)
    feedback_type: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
```

- [ ] **Step 5: Export models**

Update `backend/app/models/__init__.py`:

```python
from app.models.chat import ChatMessage, ChatSession
from app.models.meal_record import MealRecord
from app.models.recipe_feedback import RecipeFeedback
from app.models.recipe_plan import RecipePlan
from app.models.user import User
from app.models.user_memory import UserMemory
from app.models.user_profile import UserProfile

__all__ = [
    "ChatMessage",
    "ChatSession",
    "MealRecord",
    "RecipeFeedback",
    "RecipePlan",
    "User",
    "UserMemory",
    "UserProfile",
]
```

- [ ] **Step 6: Create profile schemas**

Create `backend/app/schemas/profile.py`:

```python
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
```

- [ ] **Step 7: Run targeted test and verify import advances**

Run:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest tests/test_c_side_profile_memory_recommendation.py -q
```

Expected: tests still fail because `/api/profile` is not registered, but model import errors are gone.

---

### Task 3: Profile Service And API

**Files:**
- Create: `backend/app/services/profile_service.py`
- Create: `backend/app/api/profile.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: new models and schemas from Task 2.
- Produces: `profile_service`, `/api/profile`, memory confirm/reject, recipe plan listing, feedback creation.

- [ ] **Step 1: Implement service helpers**

Create `backend/app/services/profile_service.py` with JSON normalization, model conversion, and tag utilities:

```python
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
```

- [ ] **Step 2: Implement profile CRUD and response bundle**

Add to `profile_service.py`:

```python
class CSideProfileService:
    def get_or_create_profile(self, *, db: Session, user_id: int) -> UserProfile:
        profile = db.execute(select(UserProfile).where(UserProfile.user_id == user_id)).scalar_one_or_none()
        if profile is not None:
            return profile
        profile = UserProfile(user_id=user_id)
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
```

- [ ] **Step 3: Implement strict memory extraction and decisions**

Add to `profile_service.py`:

```python
    def extract_memory_candidates(self, text: str) -> list[MemoryCandidate]:
        content = " ".join(text.strip().split())
        if not content:
            return []
        candidates: list[MemoryCandidate] = []
        patterns = [
            ("allergy", r"(?:我对)?([\u4e00-\u9fa5A-Za-z0-9]{1,12})过敏"),
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
                if value:
                    candidates.append(MemoryCandidate(memory_type=memory_type, content=value))
        unique: list[MemoryCandidate] = []
        seen: set[tuple[str, str]] = set()
        for item in candidates:
            key = (item.memory_type, item.content)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def save_pending_memories(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        text: str,
    ) -> list[UserMemory]:
        saved: list[UserMemory] = []
        for candidate in self.extract_memory_candidates(text):
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
                status="pending",
                source_session_id=session_id,
            )
            db.add(row)
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
```

- [ ] **Step 4: Implement recommendation context, plan saving, and feedback**

Add to `profile_service.py`:

```python
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
```

Add these private helpers and singleton:

```python
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


profile_service = CSideProfileService()
```

- [ ] **Step 5: Create API router**

Create `backend/app/api/profile.py`:

```python
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.profile import RecipeFeedbackCreate, RecipeFeedbackResponse, UserProfileResponse, UserProfileUpdate
from app.services.profile_service import profile_service

router = APIRouter(prefix="/api/profile", tags=["C端个人档案"])


@router.get("", response_model=UserProfileResponse)
def get_profile_bundle(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return profile_service.get_profile_bundle(db=db, user_id=current_user.id)


@router.put("", response_model=UserProfileResponse)
def update_profile(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return profile_service.update_profile(db=db, user_id=current_user.id, payload=payload)


@router.post("/memories/{memory_id}/confirm", response_model=UserProfileResponse)
def confirm_memory(
    memory_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return profile_service.confirm_memory(db=db, user_id=current_user.id, memory_id=memory_id)


@router.post("/memories/{memory_id}/reject", response_model=UserProfileResponse)
def reject_memory(
    memory_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return profile_service.reject_memory(db=db, user_id=current_user.id, memory_id=memory_id)


@router.post("/recipe-feedbacks", response_model=RecipeFeedbackResponse, status_code=status.HTTP_201_CREATED)
def create_recipe_feedback(
    payload: RecipeFeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return profile_service.create_recipe_feedback(db=db, user_id=current_user.id, payload=payload)
```

- [ ] **Step 6: Register router**

Modify `backend/app/main.py`:

```python
from app.api.profile import router as profile_router
```

After chat router:

```python
app.include_router(profile_router)
```

- [ ] **Step 7: Run tests and verify profile tests move forward**

Run:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest tests/test_c_side_profile_memory_recommendation.py -q
```

Expected: profile endpoint tests pass or fail only on chat integration/recommendation assertions.

---

### Task 4: Chat Integration And Recommendation Context

**Files:**
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/schemas/chat.py`
- Modify: `backend/app/agents/workflow_agents.py`

**Interfaces:**
- Consumes: `profile_service.save_pending_memories`, `profile_service.build_recommendation_context`, `profile_service.save_recipe_plan`.
- Produces: chat-created pending memories, profile-loaded workflow state, saved recipe plans, and feedback-aware rule fallback.

- [ ] **Step 1: Add recommendation fields to `WorkflowState`**

Modify `backend/app/schemas/chat.py` `WorkflowState`:

```python
    recommendation_context: dict = Field(default_factory=dict)
```

- [ ] **Step 2: Load profile context when creating or hydrating sessions**

In `backend/app/services/chat_service.py`, import:

```python
from app.services.profile_service import profile_service
```

Update `_apply_user_profile_to_state` to include age-independent profile fields:

```python
    def _apply_user_profile_to_state(self, *, db: Session, user_id: int, state: WorkflowState) -> None:
        profile = db.execute(select(UserProfile).where(UserProfile.user_id == user_id)).scalar_one_or_none()
        if profile is None:
            return
        context = profile_service.build_recommendation_context(db=db, user_id=user_id)
        state.goal = context.goal
        state.allergy = context.allergies
        state.diet_preference = list(dict.fromkeys([*context.preferences, *context.taboos]))
        state.disease = context.health_concerns
        state.recommendation_context = context.model_dump()
        if profile.medical_report_text:
            self._apply_medical_report_to_state(state, profile.medical_report_text)
            state.goal = context.goal
            state.allergy = context.allergies
            state.diet_preference = list(dict.fromkeys([*context.preferences, *context.taboos]))
            state.disease = context.health_concerns
            state.recommendation_context = context.model_dump()
```

- [ ] **Step 3: Save pending memories after user messages**

After each `_append_user_message` call in user-input paths, add:

```python
profile_service.save_pending_memories(
    db=db,
    user_id=user_id,
    session_id=session_id,
    text=cleaned_content_or_route_message,
)
```

Use the actual local message variable in each path:

- `append_message`: `cleaned_content`
- `stream_message`: `cleaned_content`
- `_stream_pdf_message`: skip memory extraction because the message is file-routing text.
- `_stream_single_image_message`: `cleaned_content`
- `_stream_meal_image_pair_message`: `route_message`
- `append_message_with_file`: `cleaned_content`
- `append_message_with_files`: `route_message`

Do not commit immediately after saving pending memories; let the surrounding message transaction commit.

- [ ] **Step 4: Refresh recommendation context before agent execution**

Before calling `self.master_agent.handle_message` or `self.master_agent.stream_message`, add:

```python
context = profile_service.build_recommendation_context(db=db, user_id=user_id)
workflow_state.goal = context.goal or workflow_state.goal
workflow_state.allergy = context.allergies
workflow_state.diet_preference = list(dict.fromkeys([*context.preferences, *context.taboos]))
workflow_state.disease = list(dict.fromkeys([*workflow_state.disease, *context.health_concerns]))
workflow_state.recommendation_context = context.model_dump()
```

- [ ] **Step 5: Save recipe plans after recipe replies**

Create a helper in `chat_service.py`:

```python
    def _save_recipe_plan_if_available(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        workflow_state: WorkflowState,
        assistant_content: str,
    ) -> None:
        route_intent = workflow_state.last_route.intent if workflow_state.last_route else ""
        if route_intent != "recipe_generation":
            return
        plan_type = "week" if "周" in assistant_content or any(item.day_label for item in workflow_state.recipe_plan) else "today"
        if workflow_state.recipe_plan:
            plan_content = {
                "items": [item.model_dump(mode="json") for item in workflow_state.recipe_plan],
                "markdown": assistant_content,
            }
        else:
            plan_content = {"items": [], "markdown": assistant_content}
        profile_service.save_recipe_plan(
            db=db,
            user_id=user_id,
            session_id=session_id,
            plan_type=plan_type,
            plan_content=plan_content,
            generation_basis=workflow_state.recommendation_context,
        )
```

Call it after assistant content is produced and before `db.commit()` in non-stream and stream success paths.

- [ ] **Step 6: Make rule recipe fallback feedback-aware**

In `RecipeGenerationAgent._build_rule_recipe`, read:

```python
        context = state.recommendation_context or {}
        blocked_terms = set(state.allergy) | set(state.diet_preference) | set(context.get("disliked_dishes", []))
```

After recipe templates are assigned, replace blocked dishes with safer alternatives:

```python
        for recipe in [breakfast, lunch, dinner, snack]:
            if any(term and term in recipe.dish_name for term in blocked_terms):
                recipe.nutrition_analysis = f"{recipe.nutrition_analysis} 已结合你的忌口和反馈做了避让。"
```

For this task, do not build a full recipe optimizer; the recommendation context must be visible and saved, and rule output must not ignore obvious blocked dish names.

- [ ] **Step 7: Run backend tests**

Run:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest tests/test_c_side_profile_memory_recommendation.py tests/test_phase1_account_isolation.py -q
```

Expected: all backend tests pass.

---

### Task 5: SQL Init Scripts

**Files:**
- Modify: `sql/init.sql`

**Interfaces:**
- Consumes: model fields from Tasks 2-4.
- Produces: fresh-install MySQL schema for C-side profile memory recommendation.

- [ ] **Step 1: Extend `user_profiles` SQL**

In `sql/init.sql`, add to `user_profiles`:

```sql
  `age` INT NULL COMMENT '年龄',
  `gender` VARCHAR(20) NULL COMMENT '性别',
  `height_cm` FLOAT NULL COMMENT '身高厘米',
  `weight_kg` FLOAT NULL COMMENT '体重千克',
  `diet_preference_json` TEXT NOT NULL COMMENT '饮食偏好JSON',
```

- [ ] **Step 2: Add memory, recipe plan, and feedback tables**

Add:

```sql
CREATE TABLE IF NOT EXISTS `user_memories` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id` INT NOT NULL COMMENT '用户ID',
  `memory_type` VARCHAR(32) NOT NULL COMMENT '记忆类型',
  `content` VARCHAR(120) NOT NULL COMMENT '记忆内容',
  `source` VARCHAR(32) NOT NULL DEFAULT 'chat' COMMENT '来源',
  `status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '状态',
  `source_session_id` VARCHAR(64) NULL COMMENT '来源会话ID',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_user_memories_user_status` (`user_id`, `status`),
  KEY `idx_user_memories_dedupe` (`user_id`, `memory_type`, `content`, `status`),
  CONSTRAINT `fk_user_memories_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户长期记忆表';

CREATE TABLE IF NOT EXISTS `recipe_plans` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id` INT NOT NULL COMMENT '用户ID',
  `source_session_id` VARCHAR(64) NULL COMMENT '来源会话ID',
  `plan_type` VARCHAR(20) NOT NULL DEFAULT 'unknown' COMMENT '计划类型',
  `plan_content_json` LONGTEXT NOT NULL COMMENT '食谱计划JSON',
  `generation_basis_json` LONGTEXT NOT NULL COMMENT '生成依据JSON',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_recipe_plans_user_created` (`user_id`, `created_at`),
  KEY `idx_recipe_plans_source_session_id` (`source_session_id`),
  CONSTRAINT `fk_recipe_plans_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='食谱计划表';

CREATE TABLE IF NOT EXISTS `recipe_feedbacks` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id` INT NOT NULL COMMENT '用户ID',
  `recipe_plan_id` INT NULL COMMENT '食谱计划ID',
  `dish_name` VARCHAR(120) NOT NULL COMMENT '菜品名称',
  `feedback_type` VARCHAR(32) NOT NULL COMMENT '反馈类型',
  `comment` LONGTEXT NULL COMMENT '备注',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_recipe_feedbacks_user_dish` (`user_id`, `dish_name`),
  KEY `idx_recipe_feedbacks_user_created` (`user_id`, `created_at`),
  KEY `idx_recipe_feedbacks_recipe_plan_id` (`recipe_plan_id`),
  CONSTRAINT `fk_recipe_feedbacks_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_recipe_feedbacks_recipe_plan_id` FOREIGN KEY (`recipe_plan_id`) REFERENCES `recipe_plans` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='食谱反馈表';
```

- [ ] **Step 3: Run SQL text sanity check**

Run:

```bash
for t in users user_profiles chat_sessions chat_messages meal_records user_memories recipe_plans recipe_feedbacks; do printf "%s " "$t"; rg -F -c "CREATE TABLE IF NOT EXISTS \`$t\`" sql/init.sql; done
```

Expected: each table count is `1`.

---

### Task 6: Frontend Profile API, Store, Route, And Page

**Files:**
- Create: `frontend/src/api/profile.js`
- Create: `frontend/src/stores/profile.js`
- Create: `frontend/src/views/ProfileView.vue`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/views/HomeView.vue`

**Interfaces:**
- Consumes: `/api/profile`, memory decision endpoints, `/api/profile/recipe-feedbacks`.
- Produces: authenticated C-side profile page and navigation.

- [ ] **Step 1: Create API wrapper**

Create `frontend/src/api/profile.js`:

```javascript
import request from '../utils/request'

export function getProfileBundle() {
  return request({
    url: '/api/profile',
    method: 'get'
  })
}

export function updateProfile(data) {
  return request({
    url: '/api/profile',
    method: 'put',
    data
  })
}

export function confirmMemory(memoryId) {
  return request({
    url: `/api/profile/memories/${memoryId}/confirm`,
    method: 'post'
  })
}

export function rejectMemory(memoryId) {
  return request({
    url: `/api/profile/memories/${memoryId}/reject`,
    method: 'post'
  })
}

export function createRecipeFeedback(data) {
  return request({
    url: '/api/profile/recipe-feedbacks',
    method: 'post',
    data
  })
}
```

- [ ] **Step 2: Create Pinia store**

Create `frontend/src/stores/profile.js`:

```javascript
import { defineStore } from 'pinia'

import {
  confirmMemory,
  createRecipeFeedback,
  getProfileBundle,
  rejectMemory,
  updateProfile
} from '../api/profile'

export const useProfileStore = defineStore('profile', {
  state: () => ({
    profile: null,
    pendingMemories: [],
    confirmedMemories: [],
    recipePlans: [],
    recipeFeedbacks: [],
    loading: false,
    saving: false,
    errorMessage: ''
  }),
  actions: {
    applyBundle(bundle) {
      this.profile = bundle.profile
      this.pendingMemories = bundle.pending_memories || []
      this.confirmedMemories = bundle.confirmed_memories || []
      this.recipePlans = bundle.recipe_plans || []
      this.recipeFeedbacks = bundle.recipe_feedbacks || []
    },
    async fetchProfile() {
      this.loading = true
      this.errorMessage = ''
      try {
        const response = await getProfileBundle()
        this.applyBundle(response.data)
        return response.data
      } catch (error) {
        this.errorMessage = error.response?.data?.detail || '加载档案失败'
        throw error
      } finally {
        this.loading = false
      }
    },
    async saveProfile(payload) {
      this.saving = true
      this.errorMessage = ''
      try {
        const response = await updateProfile(payload)
        this.applyBundle(response.data)
        return response.data
      } finally {
        this.saving = false
      }
    },
    async confirm(memoryId) {
      const response = await confirmMemory(memoryId)
      this.applyBundle(response.data)
      return response.data
    },
    async reject(memoryId) {
      const response = await rejectMemory(memoryId)
      this.applyBundle(response.data)
      return response.data
    },
    async submitRecipeFeedback(payload) {
      const response = await createRecipeFeedback(payload)
      await this.fetchProfile()
      return response.data
    }
  }
})
```

- [ ] **Step 3: Add route**

Modify `frontend/src/router/index.js`:

```javascript
import ProfileView from '../views/ProfileView.vue'
```

Add before catch-all:

```javascript
  {
    path: '/profile',
    name: 'profile',
    component: ProfileView,
    meta: {
      requiresAuth: true
    }
  },
```

- [ ] **Step 4: Create profile page**

Create `frontend/src/views/ProfileView.vue` with a compact operational UI:

```vue
<template>
  <main class="profile-page">
    <section class="profile-shell">
      <header class="profile-header">
        <div>
          <span>C端健康档案</span>
          <h1>我的档案</h1>
        </div>
        <RouterLink class="back-link" to="/">返回 AI 营养师</RouterLink>
      </header>

      <p v-if="profileStore.errorMessage" class="error-text">{{ profileStore.errorMessage }}</p>

      <form v-if="form" class="profile-grid" @submit.prevent="handleSubmit">
        <section class="panel profile-form">
          <h2>基础信息</h2>
          <div class="field-grid">
            <label><span>年龄</span><input v-model.number="form.age" type="number" min="1" max="120"></label>
            <label><span>性别</span><input v-model.trim="form.gender" type="text" maxlength="20"></label>
            <label><span>身高 cm</span><input v-model.number="form.height_cm" type="number" min="50" max="260"></label>
            <label><span>体重 kg</span><input v-model.number="form.weight_kg" type="number" min="10" max="400"></label>
          </div>
          <label class="full-field"><span>饮食目标</span><input v-model.trim="form.goal" type="text" maxlength="80"></label>
          <TagEditor label="过敏" v-model="form.allergies" />
          <TagEditor label="忌口" v-model="form.taboos" />
          <TagEditor label="偏好" v-model="form.preferences" />
          <TagEditor label="健康关注点" v-model="form.health_concerns" />
          <button class="primary-button" type="submit" :disabled="profileStore.saving">
            {{ profileStore.saving ? '保存中...' : '保存档案' }}
          </button>
        </section>

        <section class="panel">
          <h2>待确认记忆</h2>
          <article v-for="memory in profileStore.pendingMemories" :key="memory.id" class="memory-item">
            <strong>{{ memoryTypeLabel(memory.memory_type) }}</strong>
            <span>{{ memory.content }}</span>
            <div class="memory-actions">
              <button type="button" @click="profileStore.confirm(memory.id)">确认</button>
              <button type="button" @click="profileStore.reject(memory.id)">忽略</button>
            </div>
          </article>
          <p v-if="!profileStore.pendingMemories.length" class="empty-text">暂无待确认记忆。</p>
        </section>

        <section class="panel">
          <h2>已确认记忆</h2>
          <div class="tag-cloud">
            <span v-for="memory in profileStore.confirmedMemories" :key="memory.id">
              {{ memoryTypeLabel(memory.memory_type) }}：{{ memory.content }}
            </span>
          </div>
          <p v-if="!profileStore.confirmedMemories.length" class="empty-text">确认后的长期偏好会显示在这里。</p>
        </section>

        <section class="panel">
          <h2>食谱反馈</h2>
          <article v-for="feedback in profileStore.recipeFeedbacks" :key="feedback.id" class="feedback-item">
            <strong>{{ feedback.dish_name }}</strong>
            <span>{{ feedbackLabel(feedback.feedback_type) }}</span>
          </article>
          <p v-if="!profileStore.recipeFeedbacks.length" class="empty-text">还没有食谱反馈。</p>
        </section>
      </form>
    </section>
  </main>
</template>
```

Add this script block under the template:

```vue
<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref, watch } from 'vue'

import { useProfileStore } from '../stores/profile'

const profileStore = useProfileStore()
const form = ref(null)

const memoryLabels = {
  goal: '目标',
  allergy: '过敏',
  taboo: '忌口',
  preference: '偏好',
  health_concern: '健康关注'
}

const feedbackLabels = {
  like: '喜欢',
  dislike: '不喜欢',
  unavailable: '食堂没有',
  too_complex: '太复杂'
}

const TagEditor = defineComponent({
  props: {
    label: {
      type: String,
      required: true
    },
    modelValue: {
      type: Array,
      default: () => []
    }
  },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    const draft = ref('')
    const tags = computed(() => props.modelValue || [])

    function addTag() {
      const value = draft.value.trim()
      if (!value || tags.value.includes(value)) {
        draft.value = ''
        return
      }
      emit('update:modelValue', [...tags.value, value])
      draft.value = ''
    }

    function removeTag(tag) {
      emit('update:modelValue', tags.value.filter((item) => item !== tag))
    }

    return () => h('div', { class: 'tag-editor' }, [
      h('span', { class: 'tag-editor__label' }, props.label),
      h('div', { class: 'tag-editor__chips' }, tags.value.map((tag) => h('button', {
        class: 'tag-chip',
        type: 'button',
        onClick: () => removeTag(tag)
      }, `${tag} ×`))),
      h('div', { class: 'tag-editor__input' }, [
        h('input', {
          value: draft.value,
          placeholder: `添加${props.label}`,
          onInput: (event) => {
            draft.value = event.target.value
          },
          onKeydown: (event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              addTag()
            }
          }
        }),
        h('button', { type: 'button', onClick: addTag }, '添加')
      ])
    ])
  }
})

onMounted(async () => {
  await profileStore.fetchProfile()
})

watch(
  () => profileStore.profile,
  (profile) => {
    if (!profile) {
      form.value = null
      return
    }
    form.value = reactive({
      age: profile.age,
      gender: profile.gender || '',
      height_cm: profile.height_cm,
      weight_kg: profile.weight_kg,
      goal: profile.goal || '',
      allergies: [...(profile.allergies || [])],
      taboos: [...(profile.taboos || [])],
      preferences: [...(profile.preferences || [])],
      health_concerns: [...(profile.health_concerns || [])]
    })
  },
  { immediate: true }
)

function memoryTypeLabel(type) {
  return memoryLabels[type] || type
}

function feedbackLabel(type) {
  return feedbackLabels[type] || type
}

async function handleSubmit() {
  if (!form.value) {
    return
  }
  await profileStore.saveProfile(form.value)
}
</script>
```

Add this scoped style block:

```vue
<style lang="scss" scoped>
.profile-page {
  min-height: 100dvh;
  padding: 18px;
  background: linear-gradient(135deg, #f0fdf4 0%, #f8fafc 100%);
}

.profile-shell {
  max-width: 1280px;
  margin: 0 auto;
}

.profile-header,
.panel {
  border: 1px solid rgba(34, 197, 94, 0.14);
  border-radius: 8px;
  background: #ffffff;
}

.profile-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 20px;
  margin-bottom: 14px;
}

.profile-header span,
.tag-editor__label {
  color: #15803d;
  font-size: 12px;
  font-weight: 700;
}

.profile-header h1,
.panel h2 {
  margin: 4px 0 0;
  color: #14532d;
}

.back-link,
.primary-button,
.memory-actions button,
.tag-editor__input button {
  border: 0;
  border-radius: 6px;
  background: #16a34a;
  color: #ffffff;
  font-weight: 700;
  text-decoration: none;
  cursor: pointer;
}

.back-link {
  padding: 9px 12px;
}

.profile-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(280px, 0.7fr);
  gap: 14px;
}

.panel {
  padding: 16px;
}

.profile-form {
  grid-row: span 3;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

label,
.full-field,
.tag-editor {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin-top: 12px;
  color: #374151;
  font-size: 13px;
  font-weight: 700;
}

input {
  height: 38px;
  padding: 0 11px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
}

.tag-editor__chips,
.tag-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag-chip,
.tag-cloud span {
  border: 0;
  border-radius: 999px;
  padding: 6px 9px;
  background: #dcfce7;
  color: #166534;
}

.tag-editor__input {
  display: flex;
  gap: 8px;
}

.tag-editor__input input {
  flex: 1;
}

.primary-button {
  width: 100%;
  height: 42px;
  margin-top: 16px;
}

.memory-item,
.feedback-item {
  display: grid;
  gap: 8px;
  padding: 10px 0;
  border-bottom: 1px solid #ecfdf5;
}

.memory-actions {
  display: flex;
  gap: 8px;
}

.memory-actions button {
  padding: 7px 10px;
}

.memory-actions button:last-child {
  background: #64748b;
}

.empty-text,
.error-text {
  color: #64748b;
}

.error-text {
  color: #dc2626;
}

@media (max-width: 900px) {
  .profile-grid {
    grid-template-columns: 1fr;
  }
}
</style>
```

- [ ] **Step 5: Add navigation from home**

Modify `frontend/src/views/HomeView.vue` feature data:

```javascript
const features = [
  {
    title: 'AI 营养师',
    agent: '当前页面',
    description: '继续对话、上传报告或记录餐食。',
    path: '/'
  },
  {
    title: '我的档案',
    agent: 'C端画像',
    description: '管理目标、忌口、过敏、偏好和待确认记忆。',
    path: '/profile'
  },
  {
    title: '餐食历史',
    agent: '稍后开放',
    description: '按日期查看餐食记录和每日营养汇总。'
  },
  {
    title: '饮食复盘',
    agent: '稍后开放',
    description: '查看最近 7 天趋势、主要问题和调整建议。'
  }
]
```

Render cards with `RouterLink` when `feature.path` exists and a disabled article otherwise.

- [ ] **Step 6: Run frontend checks**

Run:

```bash
npm run lint
npm run build
```

Expected: both pass from `frontend`.

---

### Task 7: Final Verification And Commit

**Files:**
- All files touched in Tasks 1-6.

**Interfaces:**
- Produces: verified implementation and clean git state.

- [ ] **Step 1: Run backend test suite**

Run:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run Python compile check**

Run:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m compileall -q backend/app
```

Expected: exit code `0`.

- [ ] **Step 3: Run frontend checks**

Run from `frontend`:

```bash
npm run lint
npm run build
```

Expected: both exit `0`.

- [ ] **Step 4: Run SQL table count sanity check**

Run:

```bash
for t in users user_profiles chat_sessions chat_messages meal_records user_memories recipe_plans recipe_feedbacks; do printf "%s " "$t"; rg -F -c "CREATE TABLE IF NOT EXISTS \`$t\`" sql/init.sql; done
```

Expected: every line ends in `1`.

- [ ] **Step 5: Run git whitespace check**

Run:

```bash
git diff --check
```

Expected: no output, exit code `0`.

- [ ] **Step 6: Commit**

Run:

```bash
git status --short
git add backend/app frontend/src sql/init.sql tests/test_c_side_profile_memory_recommendation.py docs/superpowers/plans/2026-06-24-c-side-profile-memory-recommendation.md
git commit -m "Implement C-side profile memory recommendation"
```

Expected: commit succeeds with only C-side upgrade files included.
