"""
导入流程状态定义模块
定义 LangGraph 导入图的全局状态结构 ImportGraphState，以及状态工厂函数
所有节点通过读写该状态进行数据传递
"""
import copy
from typing import TypedDict


class ImportGraphState(TypedDict):
    """
    导入图全局状态
    贯穿整个导入流程的 7 个节点，各节点从中读取输入、写回输出
    """
    # ---- 任务标识 ----
    task_id: str  # 唯一任务 ID（UUID），由上传接口生成

    # ---- 文件路径 ----
    local_file_path: str  # 上传文件的本地完整路径（含文件名）
    local_dir: str  # 中间文件输出目录（MD、图片、JSON 等中间产物存放处）

    # ---- PDF 解析相关 ----
    pdf_path: str  # PDF 文件路径（node_pdf_to_md 写入）
    is_pdf_read_enabled: bool  # PDF 解析开关（True 时跳过 MinerU 直接读取已有 MD）

    # ---- Markdown 相关 ----
    md_path: str  # Markdown 文件路径（node_pdf_to_md 或 node_md_img 写入）
    is_md_read_enabled: bool  # MD 读取开关（True 时跳过解析直接读取已有 MD）
    md_content: str  # Markdown 正文内容（node_pdf_to_md 写入，后续节点读取）

    # ---- 文档元信息 ----
    file_title: str  # 文件标题（不含扩展名，用于 Milvus 入库标识）
    file_type: str  # 文件类型: "pdf" / "md" / "txt" / "docx" / "pptx" / "xlsx" / "html" / "image"
    source_file_path: str  # 源文件路径（保留原始上传路径）

    # ---- 主体识别 ----
    item_name: str  # 文档核心描述的产品/物品名称（node_item_name_recognition 写入）

    # ---- 切片 & 向量 ----
    chunks: list  # 文档切片列表（node_document_split 写入，每个元素为 dict）
    embeddings: list  # 向量化后的切片列表（node_bge_embedding 写入，含 dense_vector / sparse_vector）

    # ---- 导入控制 ----
    skip_import: bool  # 哈希校验跳过标记（文件未变化时跳过重复导入）
    is_update: bool  # 是否为更新导入（True 时先删除旧数据再写入）
    file_hash: str  # 文件 SHA-256 哈希值（用于去重判断）


# 默认状态模板（所有字段的初始值）
default_state: ImportGraphState = {
    'task_id': '',
    'local_file_path': '',
    'local_dir': '',
    'pdf_path': '',
    'is_pdf_read_enabled': False,
    'md_path': '',
    'is_md_read_enabled': False,
    'file_title': '',
    'md_content': '',
    'item_name': '',
    'chunks': [],
    'embeddings': [],
    'skip_import': False,
    'is_update': False,
    'file_hash': '',
    'file_type': '',
    'source_file_path': '',
}


def create_default_state(**overriders) -> ImportGraphState:
    """
    创建默认状态并覆盖指定字段
    :param overriders: 需要覆盖的字段键值对，如 task_id="xxx", local_file_path="/path/to/file"
    :return: 填充好的 ImportGraphState
    """
    copy_state: ImportGraphState = copy.deepcopy(default_state)
    copy_state.update(**overriders)
    return copy_state


def get_default_state() -> ImportGraphState:
    """获取默认状态的深拷贝（不影响模板本身）"""
    return copy.deepcopy(default_state)
