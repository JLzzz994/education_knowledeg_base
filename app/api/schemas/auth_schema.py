"""
认证服务 Pydantic 模型定义
定义登录、注册、Token、用户信息、会话列表、历史记录等接口的请求体和响应体结构
对应接口设计文档中的认证相关数据模型
"""
from pydantic import BaseModel, Field
from typing import Optional


# ==================== 请求体模型 ====================

class LoginRequest(BaseModel):
    """用户登录请求体"""
    username: str = Field(..., min_length=2, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")


class RegisterRequest(BaseModel):
    """用户注册请求体"""
    username: str = Field(..., min_length=2, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    email: Optional[str] = Field(None, description="邮箱（可选）")


class WhitelistRequest(BaseModel):
    """添加白名单用户请求体"""
    user_id: str = Field(..., description="目标用户 ID")


# ==================== 响应体模型 ====================

class TokenData(BaseModel):
    """Token 响应数据"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserInfo(BaseModel):
    """用户信息响应数据"""
    user_id: str
    username: str
    email: Optional[str] = None
    role: str = "user"
    created_at: Optional[str] = None


class UserListItem(BaseModel):
    """用户列表项"""
    user_id: str
    username: str
    email: Optional[str] = None
    role: str
    created_at: Optional[str] = None


class ApiResponse(BaseModel):
    """通用 API 响应体"""
    code: int = 200
    message: str = "success"
    data: Optional[dict] = None


# ==================== 会话 & 历史响应模型 ====================

class SessionItem(BaseModel):
    """会话列表项：包含会话 ID、最后活跃时间、消息数、最后查询内容、涉及的条目名"""
    session_id: str
    last_active: float = 0.0
    message_count: int = 0
    last_query: str = ""
    item_names: list[str] = []


class SessionListResponse(BaseModel):
    """用户会话列表响应体"""
    code: int = 200
    user_id: str = ""
    sessions: list[SessionItem] = []


class HistoryItem(BaseModel):
    """历史消息项：包含消息 ID、会话 ID、角色、文本内容、条目名、时间戳"""
    id: str
    session_id: str
    role: str
    text: str
    item_names: list[str] = []
    ts: float = 0.0


class HistoryListResponse(BaseModel):
    """用户历史消息列表响应体（分页）"""
    code: int = 200
    total: int = 0
    page: int = 1
    page_size: int = 50
    items: list[HistoryItem] = []
