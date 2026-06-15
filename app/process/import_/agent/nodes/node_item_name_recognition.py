"""
主体名称识别节点
职责: 通过 LLM 识别文档核心描述的产品/物品名称，并将主体名写入 Milvus kb_item_names 集合
写入 state: item_name（识别出的主体名称），chunks 中每个切片补充 item_name 字段
"""
from app.shared.runtime.logger import node_log
from app.shared.utils.task_utils import add_done_task, add_running_task
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.item_name_service import recognize_and_index_item_name
from app.shared.runtime.logger import logger


@node_log("node_item_name_recognition")
def node_item_name_recognition(state: ImportGraphState) -> ImportGraphState:
    """
    主体名称识别节点
    1. 标记节点开始运行
    2. 取前 K 个切片构建上下文，调用 LLM 识别主体名称
    3. 将主体名写入每个切片的 item_name 字段
    4. 生成主体名向量并 upsert 到 Milvus kb_item_names 集合
    5. 标记节点完成
    """
    add_running_task(state["task_id"], "node_item_name_recognition")
    state = recognize_and_index_item_name(state)
    add_done_task(state["task_id"], "node_item_name_recognition")
    return state