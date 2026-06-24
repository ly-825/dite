import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserInfo, UserLogin

router = APIRouter(prefix="/api/auth", tags=["认证"])


def build_placeholder_email(username: str) -> str:
    """为免邮箱注册生成内部占位邮箱。"""
    local_part = re.sub(r"[^a-zA-Z0-9._-]+", "-", username.strip().lower()).strip(".-_")
    if not local_part:
        local_part = "user"
    return f"{local_part}@users.diet-delushan.com"


@router.post("/register", response_model=UserInfo, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    """注册新用户。"""
    email = str(payload.email) if payload.email else build_placeholder_email(payload.username)
    existed_user = db.execute(
        select(User).where(
            or_(User.username == payload.username, User.email == email)
        )
    ).scalar_one_or_none()

    if existed_user:
        if existed_user.username == payload.username:
            raise HTTPException(status_code=400, detail="用户名已存在")
        raise HTTPException(status_code=400, detail="邮箱已被注册")

    user = User(
        username=payload.username,
        email=email,
        password_hash=get_password_hash(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login_user(payload: UserLogin, db: Session = Depends(get_db)) -> Token:
    """用户登录并返回 JWT。"""
    user = db.execute(
        select(User).where(
            or_(User.username == payload.account, User.email == payload.account)
        )
    ).scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="账号或密码错误")

    access_token = create_access_token(str(user.id))
    return Token(access_token=access_token, user=user)


@router.get("/me", response_model=UserInfo)
def get_profile(current_user: User = Depends(get_current_user)) -> User:
    """获取当前登录用户信息。"""
    return current_user

