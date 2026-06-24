# Phase 1 Account Isolation Implementation Plan

**Goal:** Build the first PRD phase: authenticated, user-scoped chat/report/meal data.

**Architecture:** Keep the existing FastAPI/Vue structure. Add SQLAlchemy persistence for chat/profile data and require current-user dependencies on chat APIs. Preserve the existing LangGraph workflow by serializing `WorkflowState` to session rows.

**Tech Stack:** FastAPI, SQLAlchemy 2, Pydantic v2, MySQL/PyMySQL, Vue 3, Pinia, Vue Router, Vite.

## Global Constraints

- Do not implement B-side organization/canteen features in this phase.
- Do not commit runtime uploads, reports, images, caches, or `.env` files.
- Preserve the existing SSE response contract used by `frontend/src/utils/streamRequest.js`.
- Use TDD for backend isolation behavior before production changes.

---

### Task 1: Backend Isolation Tests

**Files:**
- Create: `tests/test_phase1_account_isolation.py`

**Interfaces:**
- Consumes: `app.main.app`, `app.db.session.get_db`, `app.db.base.Base`
- Produces: test coverage for auth-required chat APIs, user-scoped sessions, and user-scoped medical reports.

- [x] Write tests using a temporary SQLite database and FastAPI `TestClient`.
- [x] Verify tests fail against the current implementation.

### Task 2: Database Models

**Files:**
- Create: `backend/app/models/chat.py`
- Create: `backend/app/models/user_profile.py`
- Modify: `backend/app/models/meal_record.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `sql/init.sql`

**Interfaces:**
- Produces: `ChatSession`, `ChatMessage`, `UserProfile`, and extended `MealRecord`.

- [x] Add SQLAlchemy models with JSON stored as text for MySQL compatibility.
- [x] Import models from `models/__init__.py`.
- [x] Extend SQL init scripts for first-phase tables.

### Task 3: User-Scoped Chat Service

**Files:**
- Modify: `backend/app/api/chat.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/agents/workflow_agents.py`

**Interfaces:**
- Consumes: current `WorkflowState`, `ChatSessionDetail`, `ChatMessage`
- Produces: chat methods that accept `db` and `user_id`.

- [x] Require `current_user` and `db` in every chat endpoint.
- [x] Hydrate/persist sessions and messages from database.
- [x] Store medical reports under user profile and user-specific report directory.
- [x] Filter diet history and meal record persistence by user.

### Task 4: Frontend Auth Restoration

**Files:**
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/stores/auth.js`
- Modify: `frontend/src/views/LoginView.vue`
- Modify: `frontend/src/views/RegisterView.vue`

**Interfaces:**
- Consumes: `/api/auth/register`, `/api/auth/login`, `/api/auth/me`
- Produces: token-gated home route and usable auth pages.

- [x] Restore login/register components in router.
- [x] Add navigation guard that redirects unauthenticated users to `/login`.
- [x] Keep existing token injection through request helpers.

### Task 5: Verification

**Files:**
- Test command targets only.

**Interfaces:**
- Produces: verified backend isolation tests and frontend build result.

- [x] Run `pytest tests/test_phase1_account_isolation.py`.
- [x] Run `npm run build` from `frontend`.
- [x] Report any remaining gaps.
