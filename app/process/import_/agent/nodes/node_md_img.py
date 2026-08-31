"""
Markdown 图片增强节点
职责: 扫描 MD 中的图片引用，调用视觉模型生成描述，上传 MinIO 替换 URL
写入 state: md_content（图片 URL 替换后）, md_path（新 MD 文件路径）
"""
from app.shared.runtime.logger import node_log
from app.shared.utils.task_utils import add_done_task, add_running_task
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.enrich_markdown_images import enrich_markdown_images


@node_log("node_md_img")
def node_md_img(state: ImportGraphState) -> ImportGraphState:
    """
    Markdown 图片增强节点
    1. 标记节点开始运行
    2. 扫描 images 目录，匹配 MD 中的图片引用
    3. 上传图片到 MinIO，调用视觉模型生成图片摘要
    4. 替换 MD 中的图片引用为图片摘要 + 远程 URL
    5. 标记节点完成
    """
    add_running_task(state["task_id"], "node_md_img")
    state = enrich_markdown_images(state)
    add_done_task(state["task_id"], "node_md_img")
    return state


if __name__ == "__main__":
    from app.shared.utils.path_util import PROJECT_ROOT
    from app.shared.runtime.logger import  logger
    import  os
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
        }
        logger.info("开始本地测试 - MD图片处理全流程")
        result_state = node_md_img(test_state)
        logger.info(f"本地测试完成 - 处理结果状态：{result_state}")