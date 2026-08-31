"""
历史记录仓储层（REQ-07 扩展）
封装 MongoDB 历史记录操作，为上层 API 提供统一接口
"""
from app.shared.clients import get_recent_messages, save_chat_message, clear_history, update_message_item_names
from app.shared.clients.mongo_history_utils import get_user_sessions, get_user_history


class HistoryRepository:
    """历史记录仓储，封装所有 MongoDB 历史记录操作"""

    def list_recent(self, session_id: str, limit: int = 10) -> list[dict]:
        """查询指定会话的最近 N 条消息"""
        return get_recent_messages(session_id, limit)

    def save_message(self,
                     *,
                     session_id: str,
                     role: str,
                     text: str,
                     rewritten_query: str = '',
                     item_names: list[str] | None = None,
                     image_urls: list[str] | None = None,
                     message_id: str | None = None,
                     user_id: str = '',
                     ) -> str:
        """保存/更新单条消息（REQ-07: 支持 user_id 关联）"""
        return save_chat_message(
            session_id=session_id,
            role=role,
            text=text,
            rewritten_query=rewritten_query,
            item_names=item_names,
            image_urls=image_urls,
            message_id=message_id,
            user_id=user_id,
        )

    def clear_session(self, session_id: str) -> int:
        """清空指定会话的历史"""
        return clear_history(session_id)

    def update_item_names(self, ids: list[str], item_names: list[str]) -> int:
        """批量更新消息的关联主体名"""
        return update_message_item_names(ids, item_names)

    # ==================== REQ-07: 用户维度查询 ====================

    def list_user_sessions(self, user_id: str, limit: int = 20) -> list[dict]:
        """获取用户的会话列表"""
        return get_user_sessions(user_id, limit)

    def list_user_history(self, user_id: str, page: int = 1, page_size: int = 50) -> tuple[list[dict], int]:
        """获取用户的历史消息（分页）"""
        return get_user_history(user_id, page, page_size)


history_repository = HistoryRepository()
