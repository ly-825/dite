# Phase 1 Account Isolation Design

## Goal

Turn the current single-user demo into a login-protected, user-isolated foundation for the PRD's first phase.

## Scope

- Require JWT authentication for chat session, message, file upload, and medical report APIs.
- Persist chat sessions and messages in MySQL instead of relying only on process memory.
- Store medical report state by `user_id`, not as one global report shared by every session.
- Store meal records by `user_id` so history queries can be scoped to the signed-in user.
- Restore the frontend login/register routes and redirect unauthenticated users away from the main app.

## Out Of Scope

- B-side organization/canteen/dish/menu/purchase/report pages.
- Full C-side profile editor and memory confirmation UI.
- Database migration tooling beyond SQLAlchemy models plus SQL scripts.

## Architecture

The existing FastAPI app keeps its router/service shape. Chat routes now depend on `get_current_user` and pass both `db` and `user_id` into `InMemoryChatService`.

`InMemoryChatService` remains the orchestration boundary for LangGraph and SSE, but session/message source of truth moves to database tables. Workflow state is serialized as JSON on `chat_sessions`. On each request the service hydrates a session from the database, runs the existing agent flow, then persists updated state and messages.

User-level medical report data is stored in `user_profiles.medical_report_text`. Runtime PDF files are stored under `backend/app/bodyreport/user_<id>/core_medical_report.pdf`.

## Data Model

- `chat_sessions`: `id`, `user_id`, `title`, `workflow_state_json`, timestamps.
- `chat_messages`: `id`, `session_id`, `user_id`, `role`, `content`, `thinking_content`, `suggested_questions_json`, `created_at`.
- `user_profiles`: `user_id`, `goal`, `allergy_json`, `taboo_json`, `health_concerns_json`, `medical_report_text`, timestamps.
- `meal_records`: add `user_id`, structured food/nutrition fields, and optional user feedback.

## Frontend Flow

Vue Router restores `/login` and `/register` as real routes. The home route requires a token and redirects to `/login` if absent. The auth store keeps using `localStorage.token`, and chat requests already attach the token through the existing request helper.

## Verification

- Backend API tests prove chat requires auth and isolates sessions/reports by user.
- Frontend build verifies route/store changes compile.
