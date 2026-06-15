import json
import sys
import time

from app.shared.runtime.logger import node_log
from app.rag.query.history_match_service import history_match_service
from app.shared.utils.task_utils import add_done_task, add_running_task


@node_log("node_history_match")
def node_history_match(state):
    """
    节点功能：历史记录查询，答案缓存
    """
    # 先登记节点开始，前端进度区可以立即感知"主体确认"已启动。
    # sys._getframe().f_code.co_name == node_item_name_confirm
    add_running_task(state["session_id"], "node_history_match", state["is_stream"])
    # 调用 rag/query service 层
    time.sleep(0.5)
    state = history_match_service(state)
    # 识别完成后写入完成列表，方便前端展示当前节点已结束。
    add_done_task(state["session_id"], "node_history_match", state["is_stream"])
    return state