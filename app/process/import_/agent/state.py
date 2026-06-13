import copy
from typing import TypedDict


class ImportGraphState(TypedDict):
    task_id: str

    local_file_path: str
    local_dir: str

    pdf_path: str
    is_pdf_read_enabled: bool
    md_path: str
    is_md_read_enabled: bool

    file_title: str
    md_content: str
    item_name: str
    chunks: list
    embeddings: list

    skip_import: bool  # 哈希校验跳过标记
    is_update: bool  # 是否为更新导入
    file_hash: str  # 文件SHA-256哈希
    file_type: str  # 新增: "pdf" / "md" / "docx" / "pptx" / "txt" / "image"
    source_file_path: str


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
    'source_file_path': ''
}


def create_default_state(**overriders) -> ImportGraphState:
    copy_state: ImportGraphState = copy.deepcopy(default_state)
    copy_state.update(**overriders)
    return copy_state


def get_default_state() -> ImportGraphState:
    return copy.deepcopy(default_state)
