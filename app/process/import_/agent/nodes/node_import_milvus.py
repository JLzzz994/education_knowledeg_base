"""
Milvus 入库节点
职责: 将向量化后的切片写入 Milvus kb_chunks 集合（先按 file_title 删除旧数据，再批量插入）
写入 state: chunks（补充 chunk_id 后的切片列表）
REQ-06: 导入完成后将文件哈希写入 MongoDB file_hashes 集合
"""
from pathlib import Path

from app.shared.runtime.logger import node_log
from app.shared.utils.task_utils import add_done_task, add_running_task
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.index_service import index_chunks
from app.shared.clients.mongo_file_hash_utils import save_file_hash


@node_log("node_import_milvus")
def node_import_milvus(state: ImportGraphState) -> ImportGraphState:
    """
    Milvus 入库节点
    1. 标记节点开始运行
    2. 删除 Milvus 中同 file_title 的旧数据（支持更新导入）
    3. 批量插入新切片（含 content、向量、元数据字段）
    4. REQ-06: 写入文件哈希记录到 MongoDB（用于后续去重）
    5. 标记节点完成
    """
    add_running_task(state["task_id"], "node_import_milvus")

    # 执行 Milvus 入库
    state = index_chunks(state)

    # REQ-06: 导入成功后写入文件哈希记录
    local_file_path = state.get("local_file_path", "")
    file_hash = state.get("file_hash", "")
    if local_file_path and file_hash:
        file_path_obj = Path(local_file_path)
        save_file_hash(
            file_name=file_path_obj.name,
            file_hash=file_hash,
            item_name=state.get("item_name", ""),
            task_id=state.get("task_id", ""),
            file_size=file_path_obj.stat().st_size if file_path_obj.exists() else 0,
        )

    add_done_task(state["task_id"], "node_import_milvus")
    return state