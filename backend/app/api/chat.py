from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.chat import ChatSessionDetail, ChatSessionSummary, CreateChatSessionRequest, SendMessageRequest
from app.services.chat_service import chat_service

router = APIRouter(prefix="/api/chat", tags=["AI 食谱助手"])


@router.get("/sessions", response_model=list[ChatSessionSummary])
def list_chat_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取聊天会话列表。"""
    return chat_service.list_sessions(db=db, user_id=current_user.id)


@router.post("/sessions", response_model=ChatSessionDetail)
def create_chat_session(
    payload: CreateChatSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建新的聊天会话。"""
    return chat_service.create_session(db=db, user_id=current_user.id, title=payload.title)


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
def get_chat_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取单个会话详情。"""
    return chat_service.get_session(db=db, user_id=current_user.id, session_id=session_id)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除当前用户的一条聊天会话及其消息，不删除长期画像或餐食记录。"""
    deleted = chat_service.delete_session(db=db, user_id=current_user.id, session_id=session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在")
    return None


@router.post("/sessions/{session_id}/messages", response_model=ChatSessionDetail)
async def send_message(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    content: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
):
    """向会话发送消息；若表单中包含文件则自动按文件消息处理。"""
    content_type = (request.headers.get("content-type") or "").lower()

    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        if files:
            file_payloads = []
            for upload in files:
                file_payloads.append(
                    {
                        "file_bytes": await upload.read(),
                        "file_name": upload.filename,
                        "content_type": upload.content_type,
                    }
                )
            return chat_service.append_message_with_files(
                db=db,
                user_id=current_user.id,
                session_id=session_id,
                content=content,
                files=file_payloads,
            )

        if file is not None:
            file_bytes = await file.read()
            return chat_service.append_message_with_file(
                db=db,
                user_id=current_user.id,
                session_id=session_id,
                content=content,
                file_bytes=file_bytes,
                file_name=file.filename,
                content_type=file.content_type,
            )

        cleaned_content = (content or "").strip()
        if not cleaned_content:
            raise HTTPException(status_code=400, detail="消息内容不能为空")
        return chat_service.append_message(db=db, user_id=current_user.id, session_id=session_id, content=cleaned_content)

    try:
        payload = SendMessageRequest.model_validate(await request.json())
    except Exception as exc:
        raise HTTPException(status_code=400, detail="消息请求格式不正确") from exc

    return chat_service.append_message(db=db, user_id=current_user.id, session_id=session_id, content=payload.content)


@router.post("/sessions/{session_id}/messages/stream")
async def stream_message(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """以流式方式返回聊天消息的 AI 回复，文本和文件统一走 SSE。"""
    content_type = (request.headers.get("content-type") or "").lower()
    stream_content = ""
    file_payloads = None

    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        stream_content = str(form.get("content") or "")
        uploads = []
        uploads.extend(item for item in form.getlist("files") if hasattr(item, "read") and hasattr(item, "filename"))
        single_upload = form.get("file")
        if hasattr(single_upload, "read") and hasattr(single_upload, "filename"):
            uploads.append(single_upload)

        if uploads:
            file_payloads = [
                {
                    "file_bytes": await upload.read(),
                    "file_name": upload.filename,
                    "content_type": upload.content_type,
                }
                for upload in uploads
            ]
        elif not stream_content.strip():
            raise HTTPException(status_code=400, detail="消息内容不能为空")
    else:
        try:
            payload = SendMessageRequest.model_validate(await request.json())
        except Exception as exc:
            raise HTTPException(status_code=400, detail="消息请求格式不正确") from exc
        stream_content = payload.content

    return StreamingResponse(
        chat_service.stream_message(
            db=db,
            user_id=current_user.id,
            session_id=session_id,
            content=stream_content,
            files=file_payloads,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_id}/medical-report", response_model=ChatSessionDetail)
async def upload_medical_report(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    report_text: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
):
    """上传体检报告文本或文件，并返回信息已保存的提示。"""
    file_bytes = await file.read() if file else None
    file_name = file.filename if file else None
    return chat_service.upload_medical_report(
        db=db,
        user_id=current_user.id,
        session_id=session_id,
        report_text=report_text,
        file_bytes=file_bytes,
        file_name=file_name,
    )


