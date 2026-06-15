"""
TXT 纯文本解析服务模块
将纯文本文件直接读取为 Markdown 格式，无需外部解析服务

处理逻辑：
  1. 校验文件路径
  2. 读取文件内容（UTF-8 编码，失败时回退 GBK）
  3. 将文件名作为一级标题，内容作为正文
  4. 保存为 .md 文件，写入 state: md_content, md_path

注：TXT 文件解析后仍会经过 node_md_img 节点（enrich_markdown_images 会自动跳过无图片的情况）
"""
from pathlib import Path

from app.process.import_.agent.state import ImportGraphState
from app.shared.runtime.logger import logger, step_log
from app.shared.utils.path_util import PROJECT_ROOT


@step_log('read_txt_to_markdown')
def read_txt_to_markdown(state: ImportGraphState) -> ImportGraphState:
    """
    读取 TXT 文件并转换为 Markdown 格式

    读取 state: source_file_path, local_dir, file_type, file_title
    写入 state: md_content（Markdown 正文）, md_path（MD 文件路径）

    :param state: 导入管线状态
    :return: 更新后的 state
    :raises ValueError: source_file_path 为空
    :raises FileNotFoundError: 源文件不存在
    """
    # 1. 从 state 读取必要字段
    source_file_path = state.get('source_file_path')
    local_dir = state.get('local_dir')
    file_title = state.get('file_title', '')

    # 2. 校验源文件路径
    if not source_file_path:
        logger.error('source_file_path 为空，无法继续解析 TXT')
        raise ValueError('source_file_path 为空，无法继续解析 TXT')

    source_path_obj = Path(source_file_path)
    if not source_path_obj.is_file():
        logger.error(f'TXT 文件不存在: {source_file_path}')
        raise FileNotFoundError(f'TXT 文件不存在: {source_file_path}')

    # 3. 确定输出目录
    if not local_dir:
        logger.warning('local_dir 为空，将使用默认输出目录: /output')
        local_dir = str(PROJECT_ROOT / 'output')

    local_dir_obj = Path(local_dir)
    local_dir_obj.mkdir(parents=True, exist_ok=True)

    # 4. 读取 TXT 文件内容（UTF-8 编码）
    try:
        txt_content = source_path_obj.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        # UTF-8 解码失败时尝试 GBK 编码（中文 Windows 常见）
        logger.warning(f'UTF-8 解码失败，尝试 GBK 编码: {source_file_path}')
        txt_content = source_path_obj.read_text(encoding='gbk')

    # 5. 构造 Markdown 内容：文件名作为一级标题，内容作为正文
    md_content = f"# {file_title}\n\n{txt_content}"

    # 6. 保存为 .md 文件
    md_path_obj = local_dir_obj / f'{source_path_obj.stem}.md'
    md_path_obj.write_text(md_content, encoding='utf-8')

    # 7. 写入 state
    state['md_content'] = md_content
    state['md_path'] = str(md_path_obj)

    logger.info(f'TXT 转 Markdown 完成，MD 路径={md_path_obj}，内容长度={len(md_content)}')
    return state
