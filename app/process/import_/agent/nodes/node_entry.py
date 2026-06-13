from app.process.import_.agent.state import ImportGraphState
from app.rag.import_.entry_service import analysis_input_file
from app.shared.runtime.logger import node_log
from app.shared.utils.task_utils import add_running_task, add_done_task


@node_log('node_entry')
def node_entry(state: ImportGraphState)->ImportGraphState:
    '''
    识别文件类型，设置路由标识
    :param state:
    :return:
    '''
    add_running_task(state['task_id'], 'node_entry')
    state = analysis_input_file(state)
    add_done_task(state['task_id'], 'node_entry')
    return state
