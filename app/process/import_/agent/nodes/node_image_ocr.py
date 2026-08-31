"""
图片 OCR 识别节点
职责: 调用 MinerU 云端解析服务对图片进行 OCR 文字识别，转换为 Markdown 格式
支持格式: .jpg, .jpeg, .png, .gif, .bmp, .webp
写入 state: md_path, md_content
"""
from app.shared.runtime.logger import node_log
from app.shared.utils.task_utils import add_done_task, add_running_task
from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.mineru_parse_service import parse_file_to_markdown


@node_log("node_image_ocr")
def node_image_ocr(state: ImportGraphState) -> ImportGraphState:
    """
    图片 OCR 识别节点
    1. 标记节点开始运行
    2. 调用 MinerU 云端解析服务（上传图片 → 轮询状态 → 下载 ZIP → 解压获取 MD）
    3. MinerU 使用视觉语言模型对图片进行 OCR 文字识别
    4. 写入 state: md_path, md_content
    5. 标记节点完成
    """
    add_running_task(state["task_id"], "node_image_ocr")
    state = parse_file_to_markdown(state)
    add_done_task(state["task_id"], "node_image_ocr")
    return state
