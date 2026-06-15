"""
Word(.docx) 转 Markdown 节点
职责: 调用 MinerU 云端解析服务将 Word 文档转换为 Markdown 格式
写入 state: md_path, md_content
"""
from app.shared.runtime.logger import node_log
from app.shared.utils.task_utils import add_done_task, add_running_task
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.mineru_parse_service import parse_file_to_markdown


@node_log("node_docx_to_md")
def node_docx_to_md(state: ImportGraphState) -> ImportGraphState:
    """
    Word(.docx) 转 Markdown 节点
    1. 标记节点开始运行
    2. 调用 MinerU 云端解析服务（上传 DOCX → 轮询状态 → 下载 ZIP → 解压获取 MD）
    3. 写入 state: md_path, md_content
    4. 标记节点完成
    """
    add_running_task(state["task_id"], "node_docx_to_md")
    state = parse_file_to_markdown(state)
    add_done_task(state["task_id"], "node_docx_to_md")
    return state
