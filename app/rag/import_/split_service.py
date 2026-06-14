import json
import re
import uuid
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.config import CHUNK_MAX_SIZE, CHUNK_SIZE, CHUNK_OVERLAP

from app.shared.runtime.logger import logger, step_log

# 占位符 __PROTECTED_BLOCK_{key}__
_PROTECTED_PREFIX = "__PROTECTED_BLOCK_"
_PROTECTED_SUFFIX = "__"

# 正则 匹配所有占位符 用于批量提取
_PLACEHOLDER_RE = re.compile(rf"{_PROTECTED_PREFIX}(\w+){_PROTECTED_SUFFIX}")

@step_log("make_placeholder")
def _make_placeholder(key: str) -> str:
    '''
    生成唯一的占位符
    :param key:
    :return:
    '''
    return f"{_PROTECTED_PREFIX}{key}{_PROTECTED_SUFFIX}"

@step_log("extract_protected_blocks")
def extract_protected_blocks(md_content: str) -> tuple[str, dict[str, str]]:
    '''
    提取并保护 公式、代码块、表格 替换为占位符
    保护顺序 围栏代码块 行内代码块 块级别公式 行内公式 表格
    :param md_content:
    :return:
    '''
    protected_map: dict[str, str] = {}
    # 待匹配的正则列表
    patterns = [
        r"(```[\s\S]*?```|~~~[\s\S]*?~~~)",  # 围栏代码块
        r"`[^`\n]+`",  # 行内代码
        r"\$\$[\s\S]*?\$\$",  # 块级公式
        r"(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)",  # 行内公式
        r"(?:^\|.+\|[ \t]*\n)+(?:^\|[-:| ]+\|[ \t]*\n)(?:^\|.+\|[ \t]*\n?)+",  # 表格
    ]

    for pattern in patterns:
        matches = list(re.finditer(pattern, md_content))
        # 从后往前替换,避免位移导致索引错乱
        for match in matches:
            key = uuid.uuid4().hex[:12]
            placeholder = _make_placeholder(key)
            protected_map[placeholder] = match.group(0)
            md_content = md_content[:match.start()] + placeholder + md_content[match.end():]

    logger.info(f'提取完成,共提取{len(protected_map)}个特殊块')
    return md_content, protected_map

@step_log("restore_protected_blocks")
def restore_protected_blocks(text: str, protected_map: dict[str, str]) -> str:
    '''
    还原占位符内容
    :param text:
    :param protected_map:
    :return:
    '''
    for placeholder, original in protected_map.items():
        text = text.replace(placeholder, original)
    return text

@step_log("load_md_content")
def load_md_content(state: ImportGraphState) -> tuple[str, str, Path]:
    '''
    获取md_path md_content file_title 校验
    若 md_content为空则从文件读取 统一换行符为 \n
    :param state:
    :return:
    '''
    md_path = state.get('md_path')
    md_content = state.get('md_content')
    file_title = state.get('file_title')
    if not md_path:
        logger.error('md_path为空,无法进行文档切分')
        raise ValueError('md_path为空,无法进行文档切分')
    md_path_obj = Path(md_path)
    if not md_content:
        logger.warning(f'md_content为空,从{md_path}中读取')
        md_content = md_path_obj.read_text(encoding='utf-8')
        state['md_content'] = md_content
        if not md_content:
            logger.error('md_content为空,无法进行文档切分')
            raise ValueError('md_content为空,无法进行文档切分')
    if not file_title:
        logger.warning(f'file_title为空,从{md_path}中读取')
        file_title = md_path_obj.stem or 'default'
        state['file_title'] = file_title
    md_content = md_content.replace('\r\n', '\n').replace('\r', '\n')
    return md_content, file_title, md_path_obj

@step_log("split_by_titles")
def split_by_titles(md_content: str, file_title: str) -> list[dict]:
    '''
    根据标题级粗切
    :param md_content:
    :param file_title:
    :return:
    '''
    reg = re.compile(r"^\s*#{1,6}\s.+")
    lines = md_content.split('\n')
    chunks: list[dict] = []
    current_title = None
    current_lines = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if reg.match(line):
            # 匹配到标题,先结算上次标题内容
            if current_title and len(current_lines) > 1:
                chunks.append({
                    'title': current_title,
                    'content': '\n'.join(current_lines),
                    'file_title': file_title,
                })
            # 第一次标题,初始化
            current_title = line
            current_lines = [line]
        else:
            current_lines.append(line)
    # 因为是遇到下个标题结算，最后一个块没有下个标题,所以主动结算
    if current_title and len(current_lines) > 1:
        chunks.append({
            'title': current_title,
            'content': '\n'.join(current_lines),
            'file_title': file_title
        })

    # chunks结算是按标题,则全文没有标题
    if not chunks:
        chunks.append({
            'title': 'default',
            'content': md_content,
            'file_title': file_title
        })

    logger.info(f'{file_title}标题语义级切分完成,共切分{len(chunks)}个块')
    return chunks

@step_log("split_long_chunks")
def _split_long_chunks(chunk: dict, max_length: int, protected_map: dict[str, str]) -> list[dict]:
    '''
    拆分过长文本块 保证单个chunk不超过最大长度限制
    1.检查内容长度,不长则直接返回
    2.标题单独保留,只拆分内容
    3.使用语义化拆分器，按段落 按句子拆分 保证语义完整
    :param chunk:
    :param max_length:
    :return:
    '''
    content = chunk.get('content', '')
    title = chunk.get('title', '')
    body = content[len(title):].strip() if content.startswith(title) else content
    prefix = title + '\n'
    # 可用长度
    available = max_length - len(prefix)

    splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", "。", "！", "？"],
        chunk_size=available,
        chunk_overlap=CHUNK_OVERLAP,
    )
    sub_chunks = []
    for index, content in enumerate(splitter.split_text(body), start=1):
        text = content.strip()
        if not text:
            logger.warning(f'处理空行 过滤')
            continue
        if len(restore_protected_blocks(text, protected_map)) > available:
            sec_splitter = RecursiveCharacterTextSplitter(
                separators=["\n", "。", "！", "？", "，"],
                chunk_size=max(available // 2, 50),
                chunk_overlap=CHUNK_OVERLAP,
            )
            for sec_index, sec_text in enumerate(sec_splitter.split_text(text), start=1):
                sec_text = sec_text.strip()
                if not sec_text:
                    logger.warning(f'处理空行 过滤')
                    continue
                sub_chunks.append({
                    'title': f"{title}_{index}_{sec_index}",
                    'content': (prefix + sec_text).strip(),
                    'parent_title': title,
                    'part': index * 10 + sec_index,
                    'file_title': chunk.get('file_title'),
                })
        else:
            sub_chunks.append({
                'title': f"{title}_{index}",
                'content': (prefix + text).strip(),
                'parent_title': title,
                'part': index,
                'file_title': chunk.get('file_title'),
            })
    logger.info(f'完成{title}内容切分完成,共切分{len(sub_chunks)}个块')
    return sub_chunks

@step_log("split_short_chunks")
def _merge_short_chunk(final_chunks: list[dict], protected_map: dict[str, str], max_length: int, min_length: int) -> \
list[dict]:
    '''
    同一个父标题，小于600才合并， 合并后不能大于1000
    :param final_chunks: 根据语义切分后的字典
    :param max_length: 合并后不能大于1000
    :param min_length: 小于600才合并
    :return: list[dict]
    '''
    # 1 声明合并后的列表
    final_merge_trunks = []
    # 2 记录第一个指针的chunk位置
    start_chunk: dict = None
    # 3 循环处理 对后续的chunk进行合并
    for next_chunk in final_chunks:
        # 4 对第一个指针赋值
        if not start_chunk:
            start_chunk = next_chunk
            continue

        # 5 是否是同一个父标题 是否小于600
        is_lt_trunk_size = len(restore_protected_blocks(start_chunk.get('content'), protected_map)) < min_length
        is_same_parent_title = start_chunk.get('parent_title') and start_chunk.get('parent_title') == next_chunk.get(
            'parent_title')
        if is_lt_trunk_size and is_same_parent_title:
            # 6 清理next标题内容 再判断合并长度
            next_content = next_chunk['content'][len(next_chunk.get('parent_title')):]
            start_content: str = start_chunk.get('content')
            # 7 长度校验 合并后长度应小于1000
            merge_content = start_content + next_content
            if len(restore_protected_blocks(merge_content, protected_map)) <= max_length:
                start_chunk['content'] = merge_content
                logger.info(f'{start_chunk.get("title")}和{next_chunk.get("title")}合并成功')
            else:
                final_merge_trunks.append(start_chunk)
                start_chunk = next_chunk
                continue
        else:
            # start_chunk<600 但是 不同父标题 存start_chunk 指向next_chunk
            # start_chunk>600  同父标题 , 存start_chunk 指向next_chunk
            # start_chunk>600 不同父标题 存start_chunk 指向next_chunk
            final_merge_trunks.append(start_chunk)
            start_chunk = next_chunk
    # 8 循环完 处理最后一个块
    if start_chunk:
        final_merge_trunks.append(start_chunk)
    logger.info(f'合并完成后{len(final_merge_trunks)}')
    return final_merge_trunks

@step_log("refine_chunks")
def refine_chunks(chunks: list[dict], protected_map: dict[str, str], max_length: int = CHUNK_MAX_SIZE,
                  min_length: int = CHUNK_SIZE) -> list[dict]:
    '''
    超长切 全程以真实长度计算
    保护块不切
    :param chunks: {title content file_title}
    :param protected_map: 占位符映射表
    :param max_length: 最大长度
    :param min_length: 最小长度(低于此值尝试合并)
    :return: 细切 合并后的块
    '''
    # 1 超长切
    final_chunks: list[dict] = []
    for chunk in chunks:
        content = chunk.get('content', '')
        if len(restore_protected_blocks(content, protected_map)) > max_length:
            final_chunks.extend(_split_long_chunks(chunk, max_length, protected_map))
        else:
            final_chunks.append(chunk)
    final_merge_chunks = _merge_short_chunk(final_chunks, protected_map, max_length, min_length)

    for chunk in final_merge_chunks:
        chunk.setdefault('parent_title', chunk.get('title'))
        chunk.setdefault('part', 1)
    logger.info(f'最终切分完成,共切分{len(final_merge_chunks)}个块')
    return final_merge_chunks

@step_log("backup_chunks_json")
def backup_chunks_json(final_merge_trunks: list[dict], md_path_obj: Path):
    json_path_obj = md_path_obj.parent / f'{md_path_obj.stem}.json'
    json_path_obj.write_text(json.dumps(final_merge_trunks, ensure_ascii=False, indent=4), encoding='utf-8')
    logger.info(f'chunks备份完成,备份路径{json_path_obj}')

@step_log("split_document")
def split_document(state: ImportGraphState) -> ImportGraphState:
    '''
    文档切分服务
    :param state:
    :return:
    '''
    # 1 加载并校验md_content内容
    md_content, file_title, md_path_obj = load_md_content(state)
    # 2 提取并保护公式、代码块、表格(替换为占位符)
    md_content, protected_map = extract_protected_blocks(md_content)
    # 3 按标题层级粗切
    spilt_by_titles_chunks = split_by_titles(md_content, file_title)
    # 4 对超长快细切、对短块合并 补全属性

    final_merge_trunks = refine_chunks(spilt_by_titles_chunks, protected_map)
    # 5 恢复被保护内容
    for chunk in final_merge_trunks:
        chunk['content'] = restore_protected_blocks(chunk['content'], protected_map)
    # 6 备份并回写chunks
    backup_chunks_json(final_merge_trunks, md_path_obj)
    state['chunks'] = final_merge_trunks
    return state
