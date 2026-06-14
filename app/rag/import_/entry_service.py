from pathlib import Path

from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.config import SUPPORTED_FILE_TYPES
from app.shared.runtime.logger import logger, step_log


@step_log("analysis_input_file")
def analysis_input_file(state: ImportGraphState) -> ImportGraphState:
    '''
    `local_file_path`, `task_id`
     `is_pdf_read_enabled`, `is_md_read_enabled`, `pdf_path`, `md_path`, `file_title`
     source_file_path file_type file_title
    :param state:
    :return:
    '''
    # 1 获取local_file_path  task_id
    local_file_path = state.get("local_file_path")

    # 2 todo hash校验



    if not local_file_path:
        logger.error(f'local_file_path为空,业务无法继续')
        raise ValueError(f'local_file_path为空,业务无法继续')
    local_file_path_obj = Path(local_file_path)
    state['file_type'] = local_file_path_obj.suffix.strip('.')

    if state.get('file_type') not in SUPPORTED_FILE_TYPES:
        logger.warning(f"{local_file_path}无法解析，本项目目前仅支持{''.join(SUPPORTED_FILE_TYPES)}")
        return state
    state['source_file_path'] = local_file_path
    state['file_title'] = local_file_path_obj.stem

    return state
