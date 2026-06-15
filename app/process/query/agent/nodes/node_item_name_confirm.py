import time

from app.shared.runtime.logger import node_log, logger
from app.rag.query.item_name_confirm_service import confirm_item_name
from app.shared.utils.task_utils import add_done_task, add_running_task
from app.rag.query.prompt_safety import is_safe_query

@node_log("node_item_name_confirm")
def node_item_name_confirm(state):
    """
    节点功能：确认用户问题中的核心商品名称。
    输入：state['original_query']
    输出：更新 state['item_names']
    """
    # 先登记节点开始，前端进度区可以立即感知"主体确认"已启动。
    # sys._getframe().f_code.co_name == node_item_name_confirm
    add_running_task(state["session_id"], "node_item_name_confirm", state["is_stream"])
    
    # === 提示词注入防护 ===
    original_query = state.get("original_query", "")
    is_safe, error_msg = is_safe_query(original_query)
    if not is_safe:
        logger.warning(f"检测到提示词注入攻击，session_id: {state['session_id']}, query: {original_query}")
        state["answer"] = "抱歉，您的输入包含不安全内容，我无法为您提供帮助。"
        state["is_safe_query"] = False
        add_done_task(state["session_id"], "node_item_name_confirm", state["is_stream"])
        return state
    
    state["is_safe_query"] = True
    
    # 调用 rag/query service 层
    time.sleep(0.5)
    state = confirm_item_name(state)
    # 识别完成后写入完成列表，方便前端展示当前节点已结束。
    add_done_task(state["session_id"], "node_item_name_confirm",state["is_stream"])
    return state




if __name__ == "__main__":
    mock_state = {
        "session_id": "test_session_001",
        "original_query": "HAK 180 烫金机怎么用？",
        "is_stream": False,
    }
    result_state = node_item_name_confirm(mock_state)
    print(result_state)