"""
入口节点: 文件类型识别 & 路由标识设置
职责: 从 state 中读取文件路径，识别文件类型（pdf/md/txt/docx），写入 file_type
后续由 main_graph.py 的条件路由根据 file_type 决定走向
"""
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.entry_service import analysis_input_file
from app.shared.runtime.logger import node_log
from app.shared.utils.task_utils import add_running_task, add_done_task


@node_log('node_entry')
def node_entry(state: ImportGraphState) -> ImportGraphState:
    """
    入口节点：识别文件类型，设置路由标识
    1. 标记节点开始运行（用于前端进度展示）
    2. 调用 entry_service 分析文件类型，写入 state['file_type']
    3. 标记节点完成
    """
    add_running_task(state['task_id'], 'node_entry')
    state = analysis_input_file(state)
    add_done_task(state['task_id'], 'node_entry')
    return state
