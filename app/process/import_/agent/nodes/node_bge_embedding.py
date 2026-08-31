"""
向量化节点
职责: 使用 BGE-M3 模型批量生成稠密向量和稀疏向量
写入 state: embeddings（含 dense_vector 和 sparse_vector 的切片列表）
"""
from app.shared.runtime.logger import node_log
from app.shared.utils.task_utils import add_done_task, add_running_task
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.embedding_service import generate_chunk_embeddings


@node_log("node_bge_embedding")
def node_bge_embedding(state: ImportGraphState) -> ImportGraphState:
    """
    向量化节点
    1. 标记节点开始运行
    2. 拼接 "主体名:{item_name},内容:{content}" 作为向量化文本
    3. 分批调用 BGE-M3 模型生成稠密向量（1024 维）和稀疏向量
    4. 将向量写入每个切片的 dense_vector / sparse_vector 字段
    5. 标记节点完成
    """
    add_running_task(state["task_id"], "node_bge_embedding")
    state = generate_chunk_embeddings(state)
    add_done_task(state["task_id"], "node_bge_embedding")
    return state