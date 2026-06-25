from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from queue import Empty, Queue
from threading import Lock, Thread
from typing import Any, Literal, TypedDict, cast
from uuid import uuid4
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.workflow_agents import (
    DietHistoryAnalysisAgent,
    GuardAgent,
    HealthRiskAgent,
    MasterAgent,
    MealRecordAgent,
    NutritionAnalysisAgent,
    RecommendationAgent,
    RecipeGenerationAgent,
    ReportParserAgent,
    UserProfileAgent,
)
from app.db.session import SessionLocal
from app.models.chat import ChatMessage as ChatMessageRow, ChatSession as ChatSessionRow
from app.models.meal_record import MealRecord
from app.models.user_memory import UserMemory
from app.models.user_profile import UserProfile
from app.schemas.chat import (
    ChatMessage as ChatMessageSchema,
    ChatSessionDetail,
    ChatSessionSummary,
    ConversationMemoryItem,
    UserProfileData,
    WorkflowState,
)
from app.services.llm_service import llm_service
from app.services.profile_service import MemoryCandidate, profile_service


RECENT_HISTORY_LIMIT = 3


class MessageDict(TypedDict):
    """内存消息结构。"""

    id: str
    role: Literal["user", "assistant"]
    content: str
    thinking_content: str
    created_at: datetime
    suggested_questions: list[str]


class FilePayloadDict(TypedDict):
    """上传文件载荷。"""

    file_bytes: bytes
    file_name: str | None
    content_type: str | None


class SessionDict(TypedDict):
    """内存会话结构。"""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageDict]
    workflow_state: WorkflowState


class InMemoryChatService:
    """基于内存的聊天服务，后续可平滑替换为数据库或真实大模型。"""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionDict] = {}
        self._lock = Lock()
        self._bodyreport_dir = Path(__file__).resolve().parents[1] / "bodyreport"
        self._bodyreport_dir.mkdir(parents=True, exist_ok=True)
        report_parser_agent = ReportParserAgent()
        self.report_parser_agent = report_parser_agent
        self.master_agent = MasterAgent(
            report_parser_agent=report_parser_agent,
            guard_agent=GuardAgent(),
            user_profile_agent=UserProfileAgent(),
            health_risk_agent=HealthRiskAgent(),
            nutrition_analysis_agent=NutritionAnalysisAgent(),
            recipe_generation_agent=RecipeGenerationAgent(),
            recommendation_agent=RecommendationAgent(),
            meal_record_agent=MealRecordAgent(),
            diet_history_analysis_agent=DietHistoryAnalysisAgent(),
        )

    def reset_runtime_state_for_tests(self, bodyreport_dir: Path | None = None) -> None:
        """测试用：清空进程内缓存并切换运行时文件目录。"""
        with self._lock:
            self._sessions = {}
            if bodyreport_dir is not None:
                self._bodyreport_dir = bodyreport_dir
                self._bodyreport_dir.mkdir(parents=True, exist_ok=True)

    def list_sessions(self, *, db: Session, user_id: int) -> list[ChatSessionSummary]:
        """获取所有会话摘要，按最近更新时间倒序排列。"""
        rows = db.execute(
            select(ChatSessionRow)
            .where(ChatSessionRow.user_id == user_id)
            .order_by(ChatSessionRow.updated_at.desc())
        ).scalars().all()
        return [self._to_summary(self._session_from_row(db, row)) for row in rows]

    def create_session(self, *, db: Session, user_id: int, title: str | None = None) -> ChatSessionDetail:
        """创建一个新的聊天会话，并附带一条欢迎消息。"""
        now = datetime.now()
        session_id = str(uuid4())
        session_title = title or "新的饮食计划"
        workflow_state = WorkflowState()
        self._apply_user_profile_to_state(db=db, user_id=user_id, state=workflow_state)
        welcome_message = self._build_message(
            role="assistant",
            content=self._build_welcome_message(workflow_state),
        )
        session: SessionDict = {
            "id": session_id,
            "title": session_title,
            "created_at": now,
            "updated_at": now,
            "messages": [welcome_message],
            "workflow_state": workflow_state,
        }

        with self._lock:
            self._sessions[session_id] = session
        self._persist_session_row(db=db, user_id=user_id, session=session)
        self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[welcome_message])
        db.commit()
        return self._to_detail(session)

    def get_session(self, *, db: Session, user_id: int, session_id: str) -> ChatSessionDetail:
        """根据会话 ID 获取完整消息列表。"""
        return self._to_detail(self._get_session(db=db, user_id=user_id, session_id=session_id))

    def append_message(self, *, db: Session, user_id: int, session_id: str, content: str) -> ChatSessionDetail:
        """向指定会话追加用户消息，并生成一条助手回复。"""
        cleaned_content = content.strip()
        if not cleaned_content:
            raise HTTPException(status_code=400, detail="消息内容不能为空")

        self._get_session(db=db, user_id=user_id, session_id=session_id)
        session, workflow_state = self._append_user_message(session_id=session_id, content=cleaned_content)
        self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[session["messages"][-1]])
        memory_candidates = profile_service.extract_memory_candidates(cleaned_content)
        saved_memories = self._remember_user_text(
            db=db,
            user_id=user_id,
            session_id=session_id,
            text=cleaned_content,
            candidates=memory_candidates,
        )
        self._refresh_recommendation_context(db=db, user_id=user_id, state=workflow_state)
        if self._is_memory_only_message(cleaned_content, memory_candidates):
            assistant_content = self._build_memory_saved_notice(saved_memories, memory_candidates)
            detail = self._append_assistant_message(session_id=session_id, content=assistant_content, session=session)
            self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[session["messages"][-1]])
            self._persist_session_row(db=db, user_id=user_id, session=session)
            db.commit()
            return detail
        previous_meal_record_count = len(workflow_state.meal_records)
        assistant_content = self.master_agent.handle_message(
            workflow_state,
            cleaned_content,
            session_id=session_id,
            user_id=user_id,
        )
        assistant_content = self._append_memory_saved_notice(assistant_content, saved_memories)
        self._persist_new_meal_records(
            db=db,
            user_id=user_id,
            session_id=session_id,
            workflow_state=workflow_state,
            previous_count=previous_meal_record_count,
        )
        detail = self._append_assistant_message(session_id=session_id, content=assistant_content, session=session)
        self._save_recipe_plan_if_available(
            db=db,
            user_id=user_id,
            session_id=session_id,
            workflow_state=workflow_state,
            assistant_content=assistant_content,
        )
        self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[session["messages"][-1]])
        self._persist_session_row(db=db, user_id=user_id, session=session)
        db.commit()
        return detail

    def stream_message(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        content: str | None = None,
        files: list[FilePayloadDict] | None = None,
    ):
        """流式返回 AI 回复内容，并在结束后写入会话。"""
        normalized_files = files or []
        if normalized_files:
            yield from self._stream_message_with_files(
                db=db,
                user_id=user_id,
                session_id=session_id,
                content=content,
                files=normalized_files,
            )
            return

        cleaned_content = (content or "").strip()
        if not cleaned_content:
            raise HTTPException(status_code=400, detail="消息内容不能为空")

        self._get_session(db=db, user_id=user_id, session_id=session_id)
        session, workflow_state = self._append_user_message(session_id=session_id, content=cleaned_content)
        self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[session["messages"][-1]])
        memory_candidates = profile_service.extract_memory_candidates(cleaned_content)
        saved_memories = self._remember_user_text(
            db=db,
            user_id=user_id,
            session_id=session_id,
            text=cleaned_content,
            candidates=memory_candidates,
        )
        self._refresh_recommendation_context(db=db, user_id=user_id, state=workflow_state)
        if self._is_memory_only_message(cleaned_content, memory_candidates):
            assistant_content = self._build_memory_saved_notice(saved_memories, memory_candidates)
            session_detail = self._append_assistant_message(
                session_id=session_id,
                content=assistant_content,
                session=session,
            )
            self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[session["messages"][-1]])
            self._persist_session_row(db=db, user_id=user_id, session=session)
            db.commit()
            yield self._build_stream_event("start", {"session_id": session_id})
            yield self._build_stream_event("delta", {"content": assistant_content})
            yield self._build_stream_event(
                "done",
                {"session_detail": session_detail.model_dump(mode="json")},
            )
            return
        previous_meal_record_count = len(workflow_state.meal_records)
        accumulated_chunks: list[str] = []
        accumulated_thinking_chunks: list[str] = []

        yield self._build_stream_event("start", {"session_id": session_id})

        try:
            for chunk in self.master_agent.stream_message(
                workflow_state,
                cleaned_content,
                session_id=session_id,
                user_id=user_id,
            ):
                chunk_type, chunk_content = self._normalize_stream_chunk(chunk)
                if not chunk_content:
                    continue
                if chunk_type == "thinking":
                    accumulated_thinking_chunks.append(chunk_content)
                    yield self._build_stream_event("thinking_delta", {"content": chunk_content})
                    continue

                accumulated_chunks.append(chunk_content)
                yield self._build_stream_event("delta", {"content": chunk_content})

            final_content = "".join(accumulated_chunks).strip()
            memory_notice = self._build_memory_saved_notice(saved_memories)
            if memory_notice:
                final_content = self._append_memory_saved_notice(final_content, saved_memories)
                yield self._build_stream_event("delta", {"content": f"\n\n{memory_notice}"})
            final_thinking_content = "".join(accumulated_thinking_chunks).strip()
            self._persist_new_meal_records(
                db=db,
                user_id=user_id,
                session_id=session_id,
                workflow_state=workflow_state,
                previous_count=previous_meal_record_count,
            )
            session_detail = self._append_assistant_message(
                session_id=session_id,
                content=final_content,
                thinking_content=final_thinking_content,
                session=session,
            )
            self._save_recipe_plan_if_available(
                db=db,
                user_id=user_id,
                session_id=session_id,
                workflow_state=workflow_state,
                assistant_content=final_content,
            )
            self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[session["messages"][-1]])
            self._persist_session_row(db=db, user_id=user_id, session=session)
            db.commit()
            yield self._build_stream_event(
                "done",
                {"session_detail": session_detail.model_dump(mode="json")},
            )
        except Exception as exc:
            yield self._build_stream_event("error", {"message": str(exc)})

    def _stream_message_with_files(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        content: str | None,
        files: list[FilePayloadDict],
    ):
        if not files:
            raise HTTPException(status_code=400, detail="请至少上传一个文件")

        if len(files) > 2:
            raise HTTPException(status_code=400, detail="当前一次最多支持上传 2 个文件")

        yield self._build_stream_event("start", {"session_id": session_id})

        try:
            if len(files) == 1:
                item = files[0]
                normalized_name = item.get("file_name") or "uploaded_file"
                suffix = Path(normalized_name).suffix.lower()
                normalized_type = (item.get("content_type") or "").lower()

                if suffix == ".pdf" or "pdf" in normalized_type:
                    yield from self._stream_pdf_message(
                        db=db,
                        user_id=user_id,
                        session_id=session_id,
                        content=content,
                        file_bytes=item["file_bytes"],
                        file_name=normalized_name,
                    )
                    return

                image_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
                if suffix in image_suffixes or normalized_type.startswith("image/"):
                    yield from self._stream_single_image_message(
                        db=db,
                        user_id=user_id,
                        session_id=session_id,
                        content=content,
                        file_bytes=item["file_bytes"],
                        file_name=normalized_name,
                    )
                    return

                raise HTTPException(status_code=400, detail="仅支持上传 PDF 或图片文件")

            yield from self._stream_meal_image_pair_message(
                db=db,
                user_id=user_id,
                session_id=session_id,
                content=content,
                files=files,
            )
        except Exception as exc:
            yield self._build_stream_event("error", {"message": str(exc)})

    def _stream_pdf_message(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        content: str | None,
        file_bytes: bytes,
        file_name: str,
    ):
        route_message = (content or "").strip() or "请帮我解析并保存这份体检报告。"
        self._get_session(db=db, user_id=user_id, session_id=session_id)
        session, workflow_state = self._append_user_message(session_id=session_id, content=route_message)
        self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[session["messages"][-1]])
        parsed_report = self.report_parser_agent.parse_upload(
            file_bytes=file_bytes,
            file_name=file_name,
        )
        self._apply_medical_report_to_state(workflow_state, parsed_report)
        if Path(file_name).suffix.lower() == ".pdf":
            self._persist_core_report(user_id=user_id, file_bytes=file_bytes)
        self._save_user_medical_report(db=db, user_id=user_id, parsed_report=parsed_report)
        self._refresh_recommendation_context(db=db, user_id=user_id, state=workflow_state)
        assistant_content = self._build_report_saved_message(parsed_report)
        yield self._build_stream_event("delta", {"content": assistant_content})

        session_detail = self._append_assistant_message(
            session_id=session_id,
            content=assistant_content,
            session=session,
        )
        self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[session["messages"][-1]])
        self._persist_session_row(db=db, user_id=user_id, session=session)
        db.commit()
        yield self._build_stream_event("done", {"session_detail": session_detail.model_dump(mode="json")})

    def _stream_single_image_message(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        content: str | None,
        file_bytes: bytes,
        file_name: str,
    ):
        cleaned_content = (content or "").strip()
        image_note = f"用户上传了图片文件：{file_name}"
        merged_message = f"{cleaned_content}\n{image_note}".strip()

        with self._lock:
            session = self._get_session(db=db, user_id=user_id, session_id=session_id)
            workflow_state = session["workflow_state"]
            user_message = self._build_message(role="user", content=merged_message)
            session["messages"].append(user_message)
            self._push_recent_history(workflow_state, user_message)
            self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[user_message])

        event_queue: Queue[dict[str, str]] = Queue()
        result_holder: dict[str, Any] = {}

        def emit_thinking(chunk: str) -> None:
            event_queue.put({"type": "thinking", "content": chunk})

        def emit_answer(chunk: str) -> None:
            event_queue.put({"type": "answer", "content": chunk})

        def run_image_analysis() -> None:
            try:
                with llm_service.stream_callbacks(
                    thinking_callback=emit_thinking,
                    answer_callback=emit_answer,
                ):
                    result_holder["content"] = llm_service.analyze_single_meal_image(
                        image_bytes=file_bytes,
                        image_name=file_name,
                        user_message=cleaned_content or None,
                        stream_answer=True,
                    )
            except Exception as exc:
                result_holder["error"] = exc
            finally:
                event_queue.put({"type": "done", "content": ""})

        worker = Thread(target=run_image_analysis, daemon=True)
        worker.start()

        accumulated_chunks: list[str] = []
        accumulated_thinking_chunks: list[str] = []
        while True:
            try:
                event = event_queue.get(timeout=0.1)
            except Empty:
                if not worker.is_alive():
                    break
                continue
            event_type = event.get("type")
            chunk_content = event.get("content") or ""
            if event_type == "done":
                break
            if not chunk_content:
                continue
            if event_type == "thinking":
                accumulated_thinking_chunks.append(chunk_content)
                yield self._build_stream_event("thinking_delta", {"content": chunk_content})
                continue
            accumulated_chunks.append(chunk_content)
            yield self._build_stream_event("delta", {"content": chunk_content})

        worker.join()
        if result_holder.get("error"):
            raise cast(Exception, result_holder["error"])

        analyzed_content = (result_holder.get("content") or "").strip()
        if analyzed_content:
            assistant_content = analyzed_content
        elif cleaned_content:
            assistant_content = (
                f"我已经收到图片《{file_name}》。\n\n"
                f"{self.master_agent.handle_message(workflow_state, cleaned_content, session_id=session_id, uploaded_image_count=1, user_id=user_id)}"
            )
        else:
            assistant_content = (
                f"我已经收到图片《{file_name}》，但当前无法稳定完成图片识别。"
                "如果你希望记录餐前餐后摄入，请一次上传两张图片；如果只是单张图片分析，也可以补一句你想让我重点看什么。"
            )

        if not accumulated_chunks:
            yield self._build_stream_event("delta", {"content": assistant_content})
        session_detail = self._append_assistant_message(
            session_id=session_id,
            content=assistant_content,
            thinking_content="".join(accumulated_thinking_chunks).strip(),
            session=session,
        )
        self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[session["messages"][-1]])
        self._persist_session_row(db=db, user_id=user_id, session=session)
        db.commit()
        yield self._build_stream_event("done", {"session_detail": session_detail.model_dump(mode="json")})

    def _stream_meal_image_pair_message(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        content: str | None,
        files: list[FilePayloadDict],
    ):
        normalized_files: list[dict[str, str | bytes]] = []
        for item in files:
            normalized_name = item.get("file_name") or "未命名图片"
            suffix = Path(normalized_name).suffix.lower()
            content_type = (item.get("content_type") or "").lower()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"} and not content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="餐前餐后对比仅支持图片文件")
            normalized_files.append(
                {
                    "file_bytes": item["file_bytes"],
                    "file_name": normalized_name,
                }
            )

        route_message = (content or "").strip() or "这是餐前和餐后两张图片，请帮我分析这顿饭实际吃了多少并记录。"
        merged_message = (
            f"{route_message}\n餐前图片：{normalized_files[0]['file_name']}\n餐后图片：{normalized_files[1]['file_name']}"
        )
        session, workflow_state = self._append_user_message(session_id=session_id, content=merged_message)
        self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[session["messages"][-1]])
        previous_meal_record_count = len(workflow_state.meal_records)
        accumulated_chunks: list[str] = []
        accumulated_thinking_chunks: list[str] = []

        for chunk in self.master_agent.stream_message(
            workflow_state,
            route_message,
            session_id=session_id,
            user_id=user_id,
            meal_before_image_bytes=cast(bytes, normalized_files[0]["file_bytes"]),
            meal_before_image_name=cast(str, normalized_files[0]["file_name"]),
            meal_after_image_bytes=cast(bytes, normalized_files[1]["file_bytes"]),
            meal_after_image_name=cast(str, normalized_files[1]["file_name"]),
            uploaded_image_count=2,
        ):
            chunk_type, chunk_content = self._normalize_stream_chunk(chunk)
            if not chunk_content:
                continue
            if chunk_type == "thinking":
                accumulated_thinking_chunks.append(chunk_content)
                yield self._build_stream_event("thinking_delta", {"content": chunk_content})
                continue
            accumulated_chunks.append(chunk_content)
            yield self._build_stream_event("delta", {"content": chunk_content})

        self._persist_new_meal_records(
            db=db,
            user_id=user_id,
            session_id=session_id,
            workflow_state=workflow_state,
            previous_count=previous_meal_record_count,
        )
        session_detail = self._append_assistant_message(
            session_id=session_id,
            content="".join(accumulated_chunks).strip(),
            thinking_content="".join(accumulated_thinking_chunks).strip(),
            session=session,
        )
        self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[session["messages"][-1]])
        self._persist_session_row(db=db, user_id=user_id, session=session)
        db.commit()
        yield self._build_stream_event("done", {"session_detail": session_detail.model_dump(mode="json")})

    def _normalize_stream_chunk(self, chunk: Any) -> tuple[Literal["answer", "thinking"], str]:
        if isinstance(chunk, dict):
            chunk_type = "thinking" if chunk.get("type") == "thinking" else "answer"
            return chunk_type, str(chunk.get("content") or "")
        return "answer", str(chunk)

    def append_message_with_file(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        content: str | None,
        file_bytes: bytes,
        file_name: str | None,
        content_type: str | None,
    ) -> ChatSessionDetail:
        normalized_name = file_name or "uploaded_file"
        suffix = Path(normalized_name).suffix.lower()
        normalized_type = (content_type or "").lower()

        if suffix == ".pdf" or "pdf" in normalized_type:
            cleaned_content = (content or "").strip()
            route_message = cleaned_content or "请帮我解析并保存这份体检报告。"
            self._get_session(db=db, user_id=user_id, session_id=session_id)
            session, workflow_state = self._append_user_message(session_id=session_id, content=route_message)
            self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[session["messages"][-1]])
            parsed_report = self.report_parser_agent.parse_upload(
                file_bytes=file_bytes,
                file_name=normalized_name,
            )
            self._apply_medical_report_to_state(workflow_state, parsed_report)
            if suffix == ".pdf":
                self._persist_core_report(user_id=user_id, file_bytes=file_bytes)
            self._save_user_medical_report(db=db, user_id=user_id, parsed_report=parsed_report)
            self._refresh_recommendation_context(db=db, user_id=user_id, state=workflow_state)
            assistant_content = self._build_report_saved_message(parsed_report)

            detail = self._append_assistant_message(
                session_id=session_id,
                content=assistant_content,
                session=session,
            )
            self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[session["messages"][-1]])
            self._persist_session_row(db=db, user_id=user_id, session=session)
            db.commit()
            return detail

        image_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        if suffix in image_suffixes or normalized_type.startswith("image/"):
            cleaned_content = (content or "").strip()
            image_note = f"用户上传了图片文件：{normalized_name}"
            merged_message = f"{cleaned_content}\n{image_note}".strip()

            with self._lock:
                session = self._get_session(db=db, user_id=user_id, session_id=session_id)

                workflow_state = session["workflow_state"]
                user_message = self._build_message(role="user", content=merged_message)
                session["messages"].append(user_message)
                self._push_recent_history(workflow_state, user_message)
                self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[user_message])

                analyzed_content = llm_service.analyze_single_meal_image(
                    image_bytes=file_bytes,
                    image_name=normalized_name,
                    user_message=cleaned_content or None,
                )
                if analyzed_content:
                    assistant_content = analyzed_content
                elif cleaned_content:
                    assistant_content = (
                        f"我已经收到图片《{normalized_name}》。\n\n"
                        f"{self.master_agent.handle_message(workflow_state, cleaned_content, session_id=session_id, uploaded_image_count=1, user_id=user_id)}"
                    )
                else:
                    assistant_content = (
                        f"我已经收到图片《{normalized_name}》，但当前无法稳定完成图片识别。"
                        "如果你希望记录餐前餐后摄入，请一次上传两张图片；如果只是单张图片分析，也可以补一句你想让我重点看什么。"
                    )

                assistant_reply = self._build_message(
                    role="assistant",
                    content=assistant_content,
                    suggested_questions=self._build_suggested_questions(workflow_state, assistant_content),
                )
                session["messages"].append(assistant_reply)
                self._push_recent_history(workflow_state, assistant_reply)
                session["updated_at"] = assistant_reply["created_at"]
                self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[assistant_reply])
                self._persist_session_row(db=db, user_id=user_id, session=session)
                db.commit()
                return self._to_detail(session)

        raise HTTPException(status_code=400, detail="仅支持上传 PDF 或图片文件")

    def append_message_with_files(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        content: str | None,
        files: list[FilePayloadDict],
    ) -> ChatSessionDetail:
        """处理多文件消息，当前主要用于餐前餐后双图分析。"""
        if not files:
            raise HTTPException(status_code=400, detail="请至少上传一个文件")

        if len(files) == 1:
            item = files[0]
            return self.append_message_with_file(
                db=db,
                user_id=user_id,
                session_id=session_id,
                content=content,
                file_bytes=item["file_bytes"],
                file_name=item.get("file_name"),
                content_type=item.get("content_type"),
            )

        if len(files) != 2:
            raise HTTPException(status_code=400, detail="餐前餐后对比目前需要上传 2 张图片")

        normalized_files: list[dict[str, str | bytes]] = []
        for item in files:
            normalized_name = item.get("file_name") or "未命名图片"
            suffix = Path(normalized_name).suffix.lower()
            content_type = (item.get("content_type") or "").lower()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"} and not content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="餐前餐后对比仅支持图片文件")
            normalized_files.append(
                {
                    "file_bytes": item["file_bytes"],
                    "file_name": normalized_name,
                }
            )

        route_message = (content or "").strip() or "这是餐前和餐后两张图片，请帮我分析这顿饭实际吃了多少并记录。"
        merged_message = (
            f"{route_message}\n餐前图片：{normalized_files[0]['file_name']}\n餐后图片：{normalized_files[1]['file_name']}"
        )
        self._get_session(db=db, user_id=user_id, session_id=session_id)
        session, workflow_state = self._append_user_message(session_id=session_id, content=merged_message)
        self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[session["messages"][-1]])
        previous_meal_record_count = len(workflow_state.meal_records)
        assistant_content = self.master_agent.handle_message(
            workflow_state,
            route_message,
            session_id=session_id,
            user_id=user_id,
            meal_before_image_bytes=cast(bytes, normalized_files[0]["file_bytes"]),
            meal_before_image_name=cast(str, normalized_files[0]["file_name"]),
            meal_after_image_bytes=cast(bytes, normalized_files[1]["file_bytes"]),
            meal_after_image_name=cast(str, normalized_files[1]["file_name"]),
            uploaded_image_count=2,
        )
        self._persist_new_meal_records(
            db=db,
            user_id=user_id,
            session_id=session_id,
            workflow_state=workflow_state,
            previous_count=previous_meal_record_count,
        )
        detail = self._append_assistant_message(
            session_id=session_id,
            content=assistant_content,
            session=session,
        )
        self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[session["messages"][-1]])
        self._persist_session_row(db=db, user_id=user_id, session=session)
        db.commit()
        return detail

    def upload_medical_report(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        report_text: str | None = None,
        file_bytes: bytes | None = None,
        file_name: str | None = None,
    ) -> ChatSessionDetail:
        """为指定会话上传并解析体检报告。"""
        with self._lock:
            session = self._get_session(db=db, user_id=user_id, session_id=session_id)

            try:
                parsed_report = self.report_parser_agent.parse_upload(
                    report_text=report_text,
                    file_bytes=file_bytes,
                    file_name=file_name,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            if not parsed_report:
                raise HTTPException(status_code=400, detail="体检报告解析失败，请重新上传。")
            self._apply_medical_report_to_state(session["workflow_state"], parsed_report)

            if file_bytes and file_name and Path(file_name).suffix.lower() == ".pdf":
                self._persist_core_report(user_id=user_id, file_bytes=file_bytes)

            self._save_user_medical_report(db=db, user_id=user_id, parsed_report=parsed_report)
            self._refresh_recommendation_context(db=db, user_id=user_id, state=session["workflow_state"])

            state = session["workflow_state"]
            report_summary = self._build_report_saved_message(parsed_report)
            assistant_reply = self._build_message(
                role="assistant",
                content=report_summary,
                suggested_questions=self._build_fallback_suggested_questions(state)[:4],
            )
            session["messages"].append(assistant_reply)
            self._push_recent_history(state, assistant_reply)
            session["updated_at"] = assistant_reply["created_at"]

            if session["title"] == "新的饮食计划":
                session["title"] = "体检报告已上传"

            self._persist_message_rows(db=db, user_id=user_id, session_id=session_id, messages=[assistant_reply])
            self._persist_session_row(db=db, user_id=user_id, session=session)
            db.commit()
            return self._to_detail(session)

    def load_persisted_report(self) -> bool:
        """第一阶段改为用户级体检报告，启动时不再加载全局报告。"""
        return False

    def _get_session(self, *, db: Session, user_id: int, session_id: str) -> SessionDict:
        row = db.execute(
            select(ChatSessionRow).where(
                ChatSessionRow.id == session_id,
                ChatSessionRow.user_id == user_id,
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        cached = self._sessions.get(session_id)
        if cached is not None:
            return cached
        return self._session_from_row(db, row)

    def _session_from_row(self, db: Session, row: ChatSessionRow) -> SessionDict:
        messages = [
            self._message_from_row(item)
            for item in db.execute(
                select(ChatMessageRow)
                .where(
                    ChatMessageRow.session_id == row.id,
                    ChatMessageRow.user_id == row.user_id,
                )
                .order_by(ChatMessageRow.created_at.asc())
            ).scalars()
        ]
        session: SessionDict = {
            "id": row.id,
            "title": row.title,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "messages": messages,
            "workflow_state": self._state_from_json(row.workflow_state_json),
        }
        self._sessions[row.id] = session
        return session

    def _message_from_row(self, row: ChatMessageRow) -> MessageDict:
        try:
            suggested_questions = json.loads(row.suggested_questions_json or "[]")
        except Exception:
            suggested_questions = []
        return {
            "id": row.id,
            "role": cast(Literal["user", "assistant"], row.role),
            "content": row.content,
            "thinking_content": row.thinking_content or "",
            "created_at": row.created_at,
            "suggested_questions": suggested_questions if isinstance(suggested_questions, list) else [],
        }

    def _persist_session_row(self, *, db: Session, user_id: int, session: SessionDict) -> None:
        row = db.get(ChatSessionRow, session["id"])
        payload = {
            "user_id": user_id,
            "title": session["title"],
            "workflow_state_json": self._state_to_json(session["workflow_state"]),
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
        }
        if row is None:
            db.add(ChatSessionRow(id=session["id"], **payload))
            return
        if row.user_id != user_id:
            raise HTTPException(status_code=404, detail="会话不存在")
        row.title = payload["title"]
        row.workflow_state_json = payload["workflow_state_json"]
        row.updated_at = payload["updated_at"]

    def _persist_message_rows(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        messages: list[MessageDict],
    ) -> None:
        for message in messages:
            if db.get(ChatMessageRow, message["id"]) is not None:
                continue
            db.add(
                ChatMessageRow(
                    id=message["id"],
                    session_id=session_id,
                    user_id=user_id,
                    role=message["role"],
                    content=message["content"],
                    thinking_content=message.get("thinking_content", ""),
                    suggested_questions_json=json.dumps(
                        message.get("suggested_questions", []),
                        ensure_ascii=False,
                    ),
                    created_at=message["created_at"],
                )
            )

    def _state_to_json(self, state: WorkflowState) -> str:
        return json.dumps(state.model_dump(mode="json"), ensure_ascii=False)

    def _state_from_json(self, payload: str | None) -> WorkflowState:
        if not payload:
            return WorkflowState()
        try:
            return WorkflowState.model_validate(json.loads(payload))
        except Exception:
            return WorkflowState()

    def _get_or_create_user_profile(self, *, db: Session, user_id: int) -> UserProfile:
        profile = db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        ).scalar_one_or_none()
        if profile is not None:
            return profile
        profile = UserProfile(user_id=user_id)
        db.add(profile)
        db.flush()
        return profile

    def _apply_user_profile_to_state(self, *, db: Session, user_id: int, state: WorkflowState) -> None:
        profile = db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        ).scalar_one_or_none()
        if profile is None:
            return
        if profile.medical_report_text:
            self._apply_medical_report_to_state(state, profile.medical_report_text)
        self._refresh_recommendation_context(db=db, user_id=user_id, state=state)

    def _refresh_recommendation_context(self, *, db: Session, user_id: int, state: WorkflowState) -> None:
        context = profile_service.build_recommendation_context(db=db, user_id=user_id)
        state.goal = context.goal or state.goal
        state.allergy = context.allergies
        state.diet_preference = list(dict.fromkeys([*context.preferences, *context.taboos]))
        state.disease = list(dict.fromkeys([*state.disease, *context.health_concerns]))
        state.recommendation_context = context.model_dump()

    def _remember_user_text(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        text: str,
        candidates: list[MemoryCandidate] | None = None,
    ) -> list[UserMemory]:
        return profile_service.save_chat_memories(
            db=db,
            user_id=user_id,
            session_id=session_id,
            text=text,
            candidates=candidates,
        )

    def _append_memory_saved_notice(self, assistant_content: str, memories: list[UserMemory]) -> str:
        notice = self._build_memory_saved_notice(memories)
        if not notice:
            return assistant_content
        return f"{assistant_content.rstrip()}\n\n{notice}"

    def _build_memory_saved_notice(
        self,
        memories: list[UserMemory],
        candidates: list[MemoryCandidate] | None = None,
    ) -> str:
        if not memories and not candidates:
            return ""
        type_labels = {
            "goal": "目标",
            "allergy": "过敏",
            "taboo": "忌口",
            "preference": "偏好",
            "health_concern": "健康关注",
        }
        parts: list[str] = []
        seen: set[tuple[str, str]] = set()
        for memory in memories:
            key = (memory.memory_type, memory.content)
            if key in seen:
                continue
            seen.add(key)
            parts.append(f"{type_labels.get(memory.memory_type, memory.memory_type)}：{memory.content}")
        for candidate in candidates or []:
            key = (candidate.memory_type, candidate.content)
            if key in seen:
                continue
            seen.add(key)
            parts.append(f"{type_labels.get(candidate.memory_type, candidate.memory_type)}：{candidate.content}")
        return f"已记住：{'；'.join(parts)}。可在「我的营养画像」里删除或修改。"

    def _is_memory_only_message(self, text: str, candidates: list[MemoryCandidate]) -> bool:
        if not candidates:
            return False
        ask_keywords = [
            "帮我",
            "生成",
            "做一份",
            "来一份",
            "安排一",
            "规划",
            "食谱",
            "菜单",
            "三餐",
            "吃什么",
            "怎么吃",
            "怎么安排",
            "推荐吃",
            "建议吃",
            "早餐",
            "午餐",
            "晚餐",
            "热量",
            "营养",
            "蛋白质",
            "碳水",
            "脂肪",
        ]
        return not any(keyword in text for keyword in ask_keywords)

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

    def _save_user_medical_report(self, *, db: Session, user_id: int, parsed_report: str) -> None:
        profile_service.update_medical_report(db=db, user_id=user_id, parsed_report=parsed_report)

    def _apply_medical_report_to_state(self, state: WorkflowState, medical_report: str) -> None:
        state.has_medical_report = True
        state.profile_completed = False
        state.health_risk_level = "unknown"
        state.medical_report = deepcopy(medical_report)
        state.user_profile = UserProfileData(medical_report_markdown=state.medical_report or "")
        state.disease = []
        state.health_risk = None
        state.nutrition_analysis = None
        state.recipe_plan = []
        state.recommendations = []
        state.goal = ""
        state.diet_preference = []
        state.allergy = []
        state.latest_profile_reply = ""
        state.latest_health_risk_reply = ""
        state.latest_recipe_reply = ""
        state.last_route = None
        state.agent_trace = []

    def _user_report_path(self, user_id: int) -> Path:
        user_dir = self._bodyreport_dir / f"user_{user_id}"
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / "core_medical_report.pdf"

    def _append_user_message(self, session_id: str, content: str) -> tuple[SessionDict, WorkflowState]:
        """先写入用户消息并返回会话上下文。"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="会话不存在")

            user_message = self._build_message(role="user", content=content)
            session["messages"].append(user_message)
            self._push_recent_history(session["workflow_state"], user_message)

            if session["title"] == "新的饮食计划":
                session["title"] = self._build_session_title(content)

            return session, session["workflow_state"]

    def _append_assistant_message(
        self,
        session_id: str,
        content: str,
        thinking_content: str = "",
        session: SessionDict | None = None,
    ) -> ChatSessionDetail:
        """写入 AI 最终回复并返回最新会话。"""
        cleaned_content = content.strip() or "暂时未生成有效回复，请稍后重试。"
        with self._lock:
            target_session = session or self._sessions.get(session_id)
            if target_session is None:
                raise HTTPException(status_code=404, detail="会话不存在")

            assistant_reply = self._build_message(
                role="assistant",
                content=cleaned_content,
                thinking_content=thinking_content.strip(),
                suggested_questions=self._build_suggested_questions(
                    target_session["workflow_state"],
                    cleaned_content,
                ),
            )
            target_session["messages"].append(assistant_reply)
            self._push_recent_history(target_session["workflow_state"], assistant_reply)
            target_session["updated_at"] = assistant_reply["created_at"]

            return self._to_detail(target_session)

    def _persist_new_meal_records(
        self,
        *,
        db: Session,
        user_id: int,
        session_id: str,
        workflow_state: WorkflowState,
        previous_count: int,
    ) -> None:
        new_records = workflow_state.meal_records[previous_count:]
        if not new_records:
            return

        for item in new_records:
            if not item.analysis_markdown:
                continue
            db.add(
                MealRecord(
                    user_id=user_id,
                    session_id=session_id,
                    recorded_at=item.recorded_at,
                    meal_type=item.meal_type,
                    foods_json=json.dumps(
                        [food.model_dump(mode="json") for food in item.consumed_items],
                        ensure_ascii=False,
                    ),
                    estimated_calories_kcal=item.estimated_calories_kcal,
                    estimated_protein_g=item.estimated_protein_g,
                    estimated_carbohydrate_g=item.estimated_carbohydrate_g,
                    estimated_fat_g=item.estimated_fat_g,
                    analysis_markdown=item.analysis_markdown,
                )
            )

    def _build_suggested_questions(self, state: WorkflowState, assistant_reply: str) -> list[str]:
        recent_user_messages = [
            {
                "content": item.content,
                "created_at": item.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
            for item in state.recent_history
            if item.role == "user"
        ][-RECENT_HISTORY_LIMIT:]
        current_user_message = recent_user_messages[-1]["content"] if recent_user_messages else ""
        generated = llm_service.generate_suggested_questions(
            workflow_state=state,
            assistant_reply=assistant_reply,
            current_user_message=current_user_message,
            recent_user_messages=recent_user_messages,
        )
        questions = list(generated or [])
        if len(questions) < 3:
            questions.extend(self._build_fallback_suggested_questions(state))

        normalized: list[str] = []
        seen: set[str] = set()
        for item in questions:
            text = " ".join(str(item).split())
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
            if len(normalized) >= 4:
                break
        return normalized

    def _build_fallback_suggested_questions(self, state: WorkflowState) -> list[str]:
        if not state.has_medical_report:
            return [
                "食堂点餐前，我先上传什么体检报告比较合适？",
                "上传 PDF 后，你会帮我看哪些健康指标？",
                "如果暂时没有体检报告，可以先告诉你哪些情况？",
            ]

        route_intent = state.last_route.intent if state.last_route else ""
        common_questions = [
            "按照我的情况，下一顿在食堂怎么选更合适？",
            "我现在点餐最需要注意什么？",
            "帮我安排今天在食堂的一日三餐。",
            "在食堂里我尽量少选哪些食物？",
        ]
        route_questions: dict[str, list[str]] = {
            "report_parsing": [
                "这份体检报告里我最该先看哪些指标？",
                "按这份报告，我在食堂点餐先改哪一点？",
                "我的情况里有哪些需要重点注意的风险？",
                "帮我安排今天在食堂的一日三餐。",
            ],
            "profile_analysis": [
                "我的个人情况还缺哪些信息要补充？",
                "按我的情况，更适合先减脂还是先控糖？",
                "我的口味偏好会怎么影响食堂点餐建议？",
                "下一步我先看风险还是先看食堂搭配？",
            ],
            "health_risk": [
                "这些风险对应到食堂点餐要避开什么？",
                "我接下来需要优先复查哪些指标？",
                "今天晚餐在食堂怎么选更稳妥？",
                "有哪些食物我这段时间先少吃？",
            ],
            "nutrition_analysis": [
                "按这个营养目标，早餐在食堂怎么搭配？",
                "我每天蛋白质在三餐里怎么分更合适？",
                "帮我把这个营养目标变成食堂三餐方案。",
                "在食堂里哪些菜更适合我现在的目标？",
            ],
            "recipe_generation": [
                "把这份方案改成更适合食堂打餐一点。",
                "这份方案适合我现在的风险情况吗？",
                "帮我安排明天在食堂的一日三餐。",
                "如果食堂没这道菜，可以换成什么？",
            ],
            "meal_record": [
                "这顿饭对我今天的目标影响大吗？",
                "按这顿饭看，我下一餐在食堂怎么调整？",
                "我今天后面两餐大概还要怎么控制？",
                "帮我继续记录下一顿餐前餐后图片。",
            ],
            "recommendation": [
                "把这些建议整理成今天在食堂的执行清单。",
                "我先从哪一条开始最容易做到？",
                "按这些建议，下一餐在食堂怎么点？",
                "这些做法坚持多久再看效果比较合适？",
            ],
        }
        return route_questions.get(route_intent, common_questions)

    def _push_recent_history(self, state: WorkflowState, message: MessageDict) -> None:
        """维护最近 6 条对话记忆，供下游 Agent 直接使用。"""
        state.recent_history.append(
            ConversationMemoryItem(
                role=message["role"],
                content=message["content"],
                created_at=message["created_at"],
            )
        )
        if len(state.recent_history) > RECENT_HISTORY_LIMIT:
            state.recent_history = state.recent_history[-RECENT_HISTORY_LIMIT:]

    def _build_stream_event(self, event_type: str, data: dict) -> str:
        """构建 SSE 数据帧。"""
        payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
        return f"data: {payload}\n\n"

    def _persist_core_report(self, *, user_id: int, file_bytes: bytes) -> None:
        """将新的用户级体检报告 PDF 写入 bodyreport/user_<id> 目录。"""
        self._user_report_path(user_id).write_bytes(file_bytes)

    def _persist_core_report_cache(self, parsed_report: str) -> None:
        """缓存 Markdown 体检报告，避免服务启动时再次请求大模型解析 PDF。"""
        return

    def _load_cached_report(self) -> str | None:
        return None

    def _parse_persisted_report_locally(self, report_path: Path) -> str:
        """启动阶段只做本地 PDF 文本解析，不调用大模型，避免拖慢服务启动。"""
        file_bytes = report_path.read_bytes()
        suffix = report_path.suffix.lower()
        if suffix == ".pdf":
            source_text = llm_service._extract_pdf_text(file_bytes)
            if not source_text:
                raise ValueError("体检报告 PDF 无法提取文本")
            return self.report_parser_agent._ensure_markdown_report(source_text)

        return self.report_parser_agent.parse_upload(
            file_bytes=file_bytes,
            file_name=report_path.name,
        )

    def _resolve_existing_report_path(self) -> Path | None:
        """获取当前系统使用的核心体检报告路径。"""
        return None

    def _sync_all_sessions_with_global_report(self) -> None:
        """将系统级核心体检报告同步到当前所有会话。"""
        return

    def _apply_global_report_to_state(self, state: WorkflowState) -> None:
        """把系统级体检报告写入会话状态，但延迟计算昂贵的衍生结果。"""
        return

    def _build_message(
        self,
        role: Literal["user", "assistant"],
        content: str,
        thinking_content: str = "",
        suggested_questions: list[str] | None = None,
    ) -> MessageDict:
        """构建统一格式的消息对象。"""
        return {
            "id": str(uuid4()),
            "role": role,
            "content": content,
            "thinking_content": thinking_content,
            "created_at": datetime.now(),
            "suggested_questions": suggested_questions or [],
        }

    def _build_session_title(self, content: str) -> str:
        """根据首条用户问题生成更易识别的标题。"""
        normalized = " ".join(content.split())
        if len(normalized) <= 14:
            return normalized
        return f"{normalized[:14]}..."

    def _build_welcome_message(self, state: WorkflowState | None = None) -> str:
        if state is not None and state.has_medical_report:
            return (
                "你好，我是食堂健康点餐助手。你可以继续提问，我会结合当前已保存的体检信息，"
                "为你提供食谱规划、营养分析、餐前餐后对比和饮食建议。"
            )

        return (
            "你好，我是食堂健康点餐助手。你可以上传体检报告 PDF，或者直接告诉我你的健康目标、"
            "饮食偏好、过敏和忌口，我会帮你做食谱规划、营养分析和点餐建议。"
        )

        if state is not None and state.has_medical_report:
            return (
                "你好，我是食堂健康点餐助手。系统已自动加载 `app/bodyreport` 目录下的核心体检报告。"
                "你现在可以直接提问，我会结合食堂常见菜品、主食、汤品和分量，给出更通俗、好执行的点餐建议。"
                "如果你需要更新健康基线，请重新上传新的体检报告 PDF，系统会覆盖旧报告。"
            )

        return (
            "你好，我是食堂健康点餐助手。为了给你更准确的食堂点餐和日常饮食建议，请先上传最近的体检报告。"
            "上传后，我会结合你的健康情况、风险提示和日常吃饭场景，给出更适合普通大众照着做的建议。"
        )
        """根据当前系统是否已有核心体检报告，返回不同的欢迎提示。"""
        if state is not None and state.has_medical_report:
            return (
                "你好，我是基于 Multi-Agent 架构的 AI 健康智能营养系统。"
                "系统已自动加载 `app/bodyreport` 目录下的核心体检报告，"
                "你现在可以直接继续提问；我会在你真正提出画像、风险、营养、食谱或推荐需求时，"
                "再基于这份体检报告按需生成对应分析结果。"
                "如果你需要更新用户身份或健康基线，请重新上传新的体检报告 PDF，系统会覆盖旧报告。"
            )

        return (
            "你好，我是基于 Multi-Agent 架构的 AI 健康智能营养系统。"
            "为了生成更加准确、安全、个性化的饮食方案，请先上传最近的体检报告。"
            "上传后，我会依次调用 Guard Agent、用户画像 Agent、健康风险 Agent、"
            "营养分析 Agent、专属食谱生成 Agent 和推荐 Agent 为你提供方案。"
        )

    def _to_summary(self, session: SessionDict) -> ChatSessionSummary:
        """将内部会话结构转换为摘要模型。"""
        messages = session["messages"]
        workflow_state = session["workflow_state"]
        last_message_preview = messages[-1]["content"][:36] if messages else None
        return ChatSessionSummary(
            id=session["id"],
            title=session["title"],
            created_at=session["created_at"],
            updated_at=session["updated_at"],
            message_count=len(messages),
            last_message_preview=last_message_preview,
            has_medical_report=workflow_state.has_medical_report,
            health_risk_level=workflow_state.health_risk_level,
        )

    def _to_detail(self, session: SessionDict) -> ChatSessionDetail:
        """将内部会话结构转换为详情模型。"""
        summary = self._to_summary(session)
        messages = [ChatMessageSchema.model_validate(deepcopy(item)) for item in session["messages"]]
        return ChatSessionDetail(
            **summary.model_dump(),
            messages=messages,
            workflow_state=deepcopy(session["workflow_state"]),
        )

    def _build_report_saved_message(self, parsed_report: str | None) -> str:
        """生成体检报告上传成功后的简洁保存提示。"""
        if parsed_report is None:
            return "体检报告信息已保存，但暂未识别到有效指标。你可以继续提问，我会基于当前已保存的信息为你提供后续分析与建议。"

        return "体检报告信息已保存成功。你可以继续提问，我会基于这份体检报告为你提供后续分析与建议。"


chat_service = InMemoryChatService()
