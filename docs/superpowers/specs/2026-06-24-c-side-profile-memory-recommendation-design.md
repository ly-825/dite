# C-Side Profile Memory Recommendation Design

## Goal

Build the next C-side upgrade as a full personalization loop: users can manage their health profile, confirm long-term memories extracted from chat, save recipe plans, give recipe feedback, and have future recipe recommendations use that context.

## Scope

- Add authenticated profile APIs for the current user's C-side health profile.
- Extend `user_profiles` with basic profile fields and preference fields needed by recommendations.
- Add `user_memories` for extracted memories with `pending`, `confirmed`, and `rejected` states.
- Add `recipe_plans` for saved generated recipe plans.
- Add `recipe_feedbacks` for dish-level user feedback.
- Add deterministic memory extraction for clear C-side statements in chat, then require user confirmation before changing long-term profile fields.
- Feed confirmed profile, confirmed memories, recent meal records, and recipe feedback into recipe generation.
- Add a C-side profile page in the frontend with profile editing and memory review.
- Add lightweight recipe feedback controls for saved recipe plan items when a generated plan can be represented structurally.

## Out Of Scope

- B-side organization, canteen, dish, menu, purchase, and report management.
- C-side "today menu" backed by B-side menu data.
- Advanced chart dashboards for meal history and seven-day review.
- Mobile-phone registration; the current username/email login remains for this step.
- Automatic confirmation of sensitive memory. User confirmation is required before extracted memory updates long-term profile fields.

## Product Behavior

### My Profile

The profile page is a signed-in C-side page reachable from the main app navigation. It shows and edits:

- Basic fields: age, gender, height, weight.
- Diet goal: one text field, such as "减脂", "增肌", "控糖", or "均衡饮食".
- Allergy tags.
- Taboo tags.
- Preference tags.
- Health concerns from report parsing or manual editing.
- Medical report status and latest stored report summary text when available.

Profile updates are scoped to the current authenticated user. Empty tag input is normalized to an empty list. Duplicate tags are removed while preserving first-seen order.

### Long-Term Memory

During chat, the backend extracts only explicit C-side personalization statements:

- Goal: "我想减脂", "目标是控糖".
- Allergy: "我对花生过敏", "海鲜过敏".
- Taboo: "我不吃香菜", "不要给我推荐西兰花".
- Preference: "我喜欢清淡", "我爱吃鸡胸肉".
- Health concern: "我尿酸偏高", "我血糖偏高".

Extracted memories are saved as `pending` rows in `user_memories`. They do not change the profile until the user confirms them. Confirming a memory updates the matching profile field. Rejecting a memory keeps the profile unchanged and prevents that exact memory from reappearing as pending.

### Recipe Plans

When the recipe workflow produces structured `recipe_plan` items, the service saves a `recipe_plans` row with:

- `plan_type`: `today` or `week`, inferred from the request and generated plan.
- `plan_content_json`: the structured recipe items.
- `generation_basis_json`: profile, memory, meal-history, and feedback context used by generation.
- `source_session_id`: the chat session that generated it.

If the model returns only markdown and no structured items, the markdown is still saved in `plan_content_json` under a `markdown` field so later UI and debugging can inspect it.

### Recipe Feedback

Users can submit dish-level feedback:

- `like`
- `dislike`
- `unavailable`
- `too_complex`

Feedback is bound to `user_id`, optional `recipe_plan_id`, `dish_name`, and `feedback_type`. New recipe generation treats `dislike`, `unavailable`, and `too_complex` as negative constraints and exposes those constraints to the recipe prompt and rule fallback.

## Backend Design

### Models

Extend `UserProfile`:

- `age`: nullable integer.
- `gender`: nullable short string.
- `height_cm`: nullable float.
- `weight_kg`: nullable float.
- `diet_preference_json`: text JSON list.

Add `UserMemory`:

- `id`: integer primary key.
- `user_id`: foreign key to users.
- `memory_type`: `goal`, `allergy`, `taboo`, `preference`, or `health_concern`.
- `content`: normalized memory content.
- `source`: `chat`, `profile`, or `report`.
- `status`: `pending`, `confirmed`, or `rejected`.
- `source_session_id`: nullable string.
- `created_at`, `updated_at`.

Add `RecipePlan`:

- `id`: integer primary key.
- `user_id`: foreign key to users.
- `source_session_id`: nullable string.
- `plan_type`: `today`, `week`, or `unknown`.
- `plan_content_json`: text JSON.
- `generation_basis_json`: text JSON.
- `created_at`.

Add `RecipeFeedback`:

- `id`: integer primary key.
- `user_id`: foreign key to users.
- `recipe_plan_id`: nullable foreign key to recipe plans.
- `dish_name`: string.
- `feedback_type`: `like`, `dislike`, `unavailable`, or `too_complex`.
- `comment`: nullable text.
- `created_at`.

### Schemas

Create profile schemas in `backend/app/schemas/profile.py`:

- `UserProfileResponse`
- `UserProfileUpdate`
- `UserMemoryResponse`
- `RecipePlanResponse`
- `RecipeFeedbackCreate`
- `RecipeFeedbackResponse`

Profile responses include pending and confirmed memories so the profile page can render both the editable profile and review queue from one page load.

### APIs

Create `backend/app/api/profile.py`:

- `GET /api/profile`: return the current user's profile plus memories.
- `PUT /api/profile`: update the current user's editable profile fields.
- `POST /api/profile/memories/{memory_id}/confirm`: confirm a pending memory and apply it to profile.
- `POST /api/profile/memories/{memory_id}/reject`: reject a pending memory.
- `GET /api/profile/recipe-plans`: list recent saved plans.
- `POST /api/profile/recipe-feedbacks`: create or replace user feedback for a dish.

All endpoints use `get_current_user` and `get_db`. Every query filters by `user_id`.

### Services

Create `backend/app/services/profile_service.py` to isolate profile, memory, plan, and feedback logic from `chat_service.py`.

Key functions:

- `get_profile_bundle(db, user_id) -> UserProfileResponse`
- `update_profile(db, user_id, payload) -> UserProfileResponse`
- `extract_memory_candidates(text) -> list[MemoryCandidate]`
- `save_pending_memories(db, user_id, session_id, text) -> list[UserMemory]`
- `confirm_memory(db, user_id, memory_id) -> UserProfileResponse`
- `reject_memory(db, user_id, memory_id) -> UserProfileResponse`
- `build_recommendation_context(db, user_id) -> RecommendationContext`
- `save_recipe_plan(db, user_id, session_id, workflow_state, assistant_content) -> RecipePlan | None`
- `create_recipe_feedback(db, user_id, payload) -> RecipeFeedback`

`chat_service.py` calls `save_pending_memories` after user messages are appended. It calls `build_recommendation_context` before recipe generation and writes the result into `WorkflowState` fields already used by agents. It calls `save_recipe_plan` after assistant recipe replies.

### Recommendation Context

The recommendation context includes:

- Profile goal, allergies, taboos, preferences, and health concerns.
- Confirmed memories grouped by type.
- Recent seven-day meal records with calories and macro totals where available.
- Negative recipe feedback grouped by dish name.
- Positive recipe feedback grouped by dish name.

This context updates the workflow state before agent execution:

- `state.goal`
- `state.allergy`
- `state.diet_preference`
- `state.disease`
- `state.recent_history` remains chat-only and is not overloaded.

The recipe agent also receives generation-basis text through the existing LLM payload path. If the LLM is disabled, rule-based recipes exclude allergy/taboo/negative-feedback dish terms where possible.

## Frontend Design

### Routes

Add a signed-in route:

- `/profile`: C-side "我的档案".

The existing home route remains the chat workspace.

### Navigation

The right-side feature panel becomes a practical C-side navigation panel:

- AI 营养师
- 我的档案
- 餐食历史
- 饮食复盘

Only "我的档案" is fully enabled in this step. Future items can remain visible as muted items if they do not navigate yet.

### Profile Page

Create `frontend/src/views/ProfileView.vue` with:

- Basic profile form.
- Tag editors for allergies, taboos, preferences, and health concerns.
- Medical report status card.
- Pending memory review list with confirm/reject actions.
- Confirmed memory list grouped by type.
- Recent saved recipe plans summary.

The visual style should stay compact and operational: restrained green accents, scan-friendly panels, no marketing hero.

### Frontend Store And API

Create:

- `frontend/src/api/profile.js`
- `frontend/src/stores/profile.js`

The profile store owns loading, saving, memory decisions, recipe plan listing, and recipe feedback submission.

## Testing

### Backend Tests

Add `tests/test_c_side_profile_memory_recommendation.py`:

- Profile APIs require login.
- Alice and Bob cannot see or update each other's profiles.
- Updating profile normalizes duplicate tags.
- Chat message "我不吃香菜" creates a pending taboo memory.
- Confirming the memory writes "香菜" to `taboo_json`.
- Rejected memory does not write to profile.
- Recipe generation context includes confirmed taboo and negative dish feedback.
- Saved recipe plans are scoped by current user.
- Recipe feedback is scoped by current user.

### Frontend Verification

- `npm run lint`
- `npm run build`

Manual browser QA can follow after implementation because this page is new UI.

## Rollout

This step is additive. Existing chat sessions and meal records continue to work. Existing `user_profiles` rows get new nullable columns and default JSON lists. SQL init scripts are updated for fresh installs; no destructive migration is required in this repo.

## Risks

- The current `chat_service.py` is large. New profile and memory logic must live in `profile_service.py`; `chat_service.py` should only orchestrate calls.
- Rule-based memory extraction can over-capture if too broad. Keep patterns strict and save as pending instead of confirmed.
- Recipe markdown from the LLM may not always map to structured `RecipeMealItem`. Save markdown fallback so feedback and plan history still have a record.
- Negative feedback constraints should guide recommendations but should not make recipe generation impossible. If all candidates are excluded, the system should explain the tradeoff and provide the least conflicting option.
