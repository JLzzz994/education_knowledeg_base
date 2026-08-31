"""
TXT 纯文本转 Markdown 节点
职责: 直接读取 TXT 文件内容，转换为 Markdown 格式（无需外部解析服务）
写入 state: md_path, md_content
"""
from app.shared.runtime.logger import node_log
from app.shared.utils.task_utils import add_done_task, add_running_task
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.txt_parse_service import read_txt_to_markdown


@node_log("node_txt_to_md")
def node_txt_to_md(state: ImportGraphState) -> ImportGraphState:
    """
    TXT 纯文本转 Markdown 节点
    1. 标记节点开始运行
    2. 直接读取 TXT 文件内容（UTF-8/GBK 编码）
    3. 将文件名作为一级标题，内容作为正文
    4. 写入 state: md_path, md_content
    5. 标记节点完成
    """
    add_running_task(state["task_id"], "node_txt_to_md")
    state = read_txt_to_markdown(state)
    add_done_task(state["task_id"], "node_txt_to_md")
    return state
