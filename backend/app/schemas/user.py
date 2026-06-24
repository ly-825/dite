from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    """注册请求参数。"""

    username: str = Field(min_length=3, max_length=20)
    email: EmailStr | None = None
    password: str = Field(min_length=6, max_length=20)


class UserLogin(BaseModel):
    """登录请求参数。"""

    account: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=6, max_length=20)


class UserInfo(BaseModel):
    """返回给前端的用户信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    created_at: datetime


class Token(BaseModel):
    """登录成功后的令牌信息。"""

    access_token: str
    token_type: str = "bearer"
    user: UserInfo

