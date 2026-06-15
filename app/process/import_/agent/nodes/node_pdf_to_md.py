"""
PDF 转 Markdown 节点
职责: 调用 MinerU 云端解析服务将 PDF 转换为 Markdown 格式
写入 state: md_path, md_content, file_title
"""
from app.shared.runtime.logger import node_log
from app.shared.utils.task_utils import add_done_task, add_running_task
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.mineru_parse_service import parse_file_to_markdown


@node_log("node_pdf_to_md")
def node_pdf_to_md(state: ImportGraphState) -> ImportGraphState:
    """
    PDF 转 Markdown 节点
    1. 标记节点开始运行
    2. 调用 MinerU 云端解析服务（上传 PDF → 轮询状态 → 下载 ZIP → 解压获取 MD）
    3. 写入 state: md_path, md_content, file_title
    4. 标记节点完成
    """
    add_running_task(state["task_id"], "node_pdf_to_md")
    state = parse_file_to_markdown(state)
    add_done_task(state["task_id"], "node_pdf_to_md")
    return state

if __name__ == "__main__":
    from app.shared.runtime.logger import logger,PROJECT_ROOT
    import os
    from app.process.import_.agent.state import create_default_state
    logger.info("===== 开始 node_pdf_to_md 节点联调测试 =====")

    source_file_path = os.path.join(PROJECT_ROOT, "doc", "hak180产品安全手册.pdf")
    test_state = create_default_state(
        task_id="test_pdf2md_task_001",
        source_file_path=source_file_path,
        local_dir=os.path.join(PROJECT_ROOT, "output"),
    )

    result = node_pdf_to_md(test_state)
    logger.info(f"source_file_path: {result['source_file_path']}")
    logger.info(f"md_path: {result['md_path']}")
    logger.info(f"md_content长度: {len(result['md_content'])}")
    logger.info("===== 结束 node_pdf_to_md 节点联调测试 =====")