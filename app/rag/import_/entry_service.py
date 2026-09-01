"""
入口服务模块 - 文件类型识别、哈希校验与路由标识设置
职责：
1. 从 state 中读取文件路径，提取文件类型和标题
2. REQ-06: 计算文件 SHA-256 哈希，查询 MongoDB 判断是否重复导入
3. 校验文件格式是否支持
支持格式: pdf, md, txt, docx, pptx, xlsx, html, image(jpg/png/...)
图片后缀统一映射为 file_type="image"
在 LangGraph 管线中作为第一个节点的底层服务，决定后续走哪个格式处理节点
"""
import hashlib
from pathlib import Path

from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.config import SUPPORTED_FILE_TYPES, IMAGE_FILE_EXTENSIONS
from app.shared.clients.mongo_file_hash_utils import find_by_file_hash, find_by_file_name
from app.shared.runtime.logger import logger, step_log


@step_log("analysis_input_file")
def analysis_input_file(state: ImportGraphState) -> ImportGraphState:
    """
    分析输入文件，提取文件类型和标题，校验是否支持该格式，执行哈希去重
    :param state: 导入管线状态，需包含 local_file_path 字段
    :return: 更新后的 state，包含 file_type、file_title、source_file_path、file_hash、skip_import、is_update
    """
    # 1. 获取文件路径（由调用方写入 state）
    local_file_path = state.get("local_file_path")

    # 2. 校验文件路径非空
    if not local_file_path:
        logger.error(f'local_file_path为空,业务无法继续')
        raise ValueError(f'local_file_path为空,业务无法继续')

    # 3. 提取文件后缀作为 file_type
    #    图片后缀（.jpg/.png 等）统一映射为 "image"，其余取后缀本身（如 "pdf"、"md"）
    local_file_path_obj = Path(local_file_path)
    suffix = local_file_path_obj.suffix.lower()
    if suffix in IMAGE_FILE_EXTENSIONS:
        state['file_type'] = 'image'
    else:
        state['file_type'] = local_file_path_obj.suffix.strip('.').lower()

    # 4. 校验文件类型是否在支持列表中，不支持则直接返回（图路由会跳到 END）
    if state.get('file_type') not in SUPPORTED_FILE_TYPES:
        logger.warning(f"{local_file_path}无法解析，本项目目前仅支持: {', '.join(sorted(SUPPORTED_FILE_TYPES))}")
        return state

    # 5. 设置源文件路径和文件标题（不含后缀的文件名）
    state['source_file_path'] = local_file_path
    state['file_title'] = local_file_path_obj.stem

    # ==================== REQ-06: 文件哈希去重 ====================
    # 6. 计算文件 SHA-256 哈希
    file_bytes = local_file_path_obj.read_bytes()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    state['file_hash'] = file_hash

    # 7. 查询 MongoDB 是否已存在相同哈希（内容完全相同 → 跳过导入）
    existing = find_by_file_hash(file_hash)
    if existing:
        state['skip_import'] = True
        logger.info(f"文件{local_file_path_obj.name}哈希已存在(主体:{existing.get('item_name','')}),跳过导入")
        return state

    # 8. 查询同名文件是否存在（同名不同内容 → 更新场景，先删旧向量再导入）
    same_name_records = find_by_file_name(local_file_path_obj.name)
    if same_name_records:
        state['is_update'] = True
        logger.info(f"文件{local_file_path_obj.name}已存在但内容变化,执行更新导入")

    return state
