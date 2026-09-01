"""
认证服务 Pydantic 模型定义
定义登录、注册、用户管理等接口的请求体和响应体

模型清单:
  请求体: LoginRequest, RegisterRequest, WhitelistRequest
  响应体: ApiResponse, TokenData, UserInfo, UserListItem
  会话/历史: SessionItem, SessionListResponse, HistoryItem, HistoryListResponse
"""
from typing import Any, Optional
from pydantic import BaseModel


# ==================== 请求体 ====================

class LoginRequest(BaseModel):
    """登录请求 — 用户名 + 密码"""
    username: str
    password: str


class RegisterRequest(BaseModel):
    """注册请求 — 用户名 + 密码 + 可选邮箱"""
    username: str
    password: str
    email: Optional[str] = None


class WhitelistRequest(BaseModel):
    """白名单操作请求 — 添加用户到白名单"""
    user_id: str


# ==================== 响应体 ====================

class TokenData(BaseModel):
    """Token 数据 — 登录成功后返回"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserInfo(BaseModel):
    """当前用户信息 — 对应 GET /auth/me"""
    user_id: str
    username: str
    role: str
    email: Optional[str] = None


class UserListItem(BaseModel):
    """用户列表项 — 管理后台用户表格使用"""
    id: str
    username: str
    role: str
    email: Optional[str] = None
    created_at: Optional[str] = None


class ApiResponse(BaseModel):
    """通用 API 响应包装"""
    code: int = 200
    message: str = "success"
    data: Optional[Any] = None


# ==================== 会话/历史 ====================

class SessionItem(BaseModel):
    """会话列表项"""
    session_id: str
    title: Optional[str] = None
    last_active: Optional[str] = None
    message_count: int = 0


class SessionListResponse(BaseModel):
    """会话列表响应"""
    sessions: list[SessionItem]


class HistoryItem(BaseModel):
    """用户历史消息项"""
    id: str
    session_id: str
    role: str
    text: str
    ts: Any = None


class HistoryListResponse(BaseModel):
    """用户历史消息列表响应"""
    items: list[HistoryItem]
    total: int = 0
