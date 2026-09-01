"""
查询服务 Pydantic 模型定义
定义智能问答接口的请求体和响应体结构

模型清单:
  请求体: QueryRequestParam, InterruptResumeParam
  响应体: QueryStreamResponse, QueryNotStreamResponse, InterruptResponse,
          HistoryCleanResponse, HistoryItemResponse, HistoryResponse
"""
from typing import Any, Optional
from pydantic import BaseModel


# ==================== 请求体 ====================

class QueryRequestParam(BaseModel):
    """
    查询请求参数 — 对应 POST /query
    - query: 用户提问内容
    - session_id: 会话 ID（可选，首次查询自动生成）
    - is_stream: 是否使用 SSE 流式模式
    - user_id: 用户 ID（REQ-07，用于历史记录关联）
    """
    query: str
    session_id: Optional[str] = None
    is_stream: bool = False
    user_id: Optional[str] = None


class InterruptResumeParam(BaseModel):
    """
    中断恢复请求参数 — 对应 POST /resume
    当 LangGraph 触发 interrupt（如主体名确认）时，用户选择后调用此接口继续执行
    - session_id: 原会话 ID
    - selected_value: 用户选择的值
    - is_stream: 是否流式模式
    """
    session_id: str
    selected_value: str
    is_stream: bool = False


# ==================== 响应体 ====================

class QueryStreamResponse(BaseModel):
    """流式查询响应 — 立即返回 session_id，前端通过 SSE 接收结果"""
    message: str
    session_id: str


class QueryNotStreamResponse(BaseModel):
    """同步查询响应 — 等待执行完成后返回完整结果"""
    message: str
    session_id: str
    answer: str = ""
    done_list: list = []
    image_urls: list = []
    interrupt: Optional[dict] = None  # 中断数据（需用户选择时非空）


class InterruptInfo(BaseModel):
    """中断信息 — 描述需要用户确认的内容和可选项"""
    title: str
    description: str
    options: list[str]
    type: str


class InterruptResponse(BaseModel):
    """中断响应 — 查询执行过程中需要用户干预时返回"""
    message: str
    session_id: str
    status: str
    interrupt: InterruptInfo


class HistoryCleanResponse(BaseModel):
    """历史记录清空响应"""
    message: str
    deleted_count: int


class HistoryItemResponse(BaseModel):
    """单条历史消息"""
    id: str
    session_id: str
    role: str
    text: str
    rewritten_query: Optional[str] = None
    item_names: list = []
    image_urls: list = []
    ts: Any = None


class HistoryResponse(BaseModel):
    """历史记录列表响应"""
    session_id: str
    items: list[HistoryItemResponse]


class SessionItemResponse(BaseModel):
    """单个会话摘要（REQ-07）"""
    session_id: str
    last_active: Any = None
    message_count: int = 0
    last_query: str = ""
    item_names: list = []


class SessionListResponse(BaseModel):
    """用户会话列表响应（REQ-07）"""
    user_id: str
    sessions: list[SessionItemResponse]


class UserHistoryResponse(BaseModel):
    """用户历史消息响应（REQ-07）"""
    user_id: str
    total: int = 0
    items: list[HistoryItemResponse]
