"""
文档切分节点
职责: 将 Markdown 长文档按标题切分、超长块二次拆分、短块合并，生成结构化切片
写入 state: chunks（切片列表，每个元素含 title/content/file_title/parent_title/part）
"""
from app.shared.runtime.logger import node_log
from app.shared.utils.task_utils import add_done_task, add_running_task
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.split_service import split_document


@node_log("node_document_split")
def node_document_split(state: ImportGraphState) -> ImportGraphState:
    """
    文档切分节点
    1. 标记节点开始运行
    2. 提取并保护公式/代码块/表格（替换为占位符）
    3. 按标题层级粗切，超长块二次拆分，短块合并
    4. 恢复保护内容，备份 JSON，写入 state['chunks']
    5. 标记节点完成
    """
    add_running_task(state["task_id"], "node_document_split")
    state = split_document(state)
    add_done_task(state["task_id"], "node_document_split")
    return state

if __name__ == '__main__':
    from app.shared.utils.path_util import PROJECT_ROOT
    from app.process.import_.agent.nodes.node_md_img import node_md_img
    from app.shared.runtime.logger import logger
    import os
    logger.info(f"本地测试 - 项目根目录：{PROJECT_ROOT}")

    test_md_name = os.path.join(r"output\hak180产品安全手册", "hak180产品安全手册.md")
    test_md_path = os.path.join(PROJECT_ROOT, test_md_name)

    if not os.path.exists(test_md_path):
        logger.error(f"本地测试 - 测试文件不存在：{test_md_path}")
        logger.info("请检查文件路径，或手动将测试MD文件放入项目根目录的output目录下")
    else:
        test_state = {
            "md_path": test_md_path,
            "task_id": "test_task_123456",
            "md_content": "",
            "file_title": "hak180产品安全手册",
            "local_dir": os.path.join(PROJECT_ROOT, "output"),
        }
        result_state = node_md_img(test_state)
        final_state = node_document_split(result_state)
        final_chunks = final_state.get("chunks", [])
        logger.info(f"测试成功：最终生成{len(final_chunks)}个有效Chunk")