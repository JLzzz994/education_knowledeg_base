from mimetypes import guess_type
from pathlib import Path
import sys
import uuid

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from starlette.middleware.cors import CORSMiddleware

from app.api.schema.query_schema import QueryRequestSchema, QueryStreamResponseSchema, QueryResponseSchema, \
    HistoryResponseSchema, HistoryItemSchema, ClearHistoryResponseSchema
from app.infra.persistence.history_repository import history_repository
from app.shared.runtime.logger import PROJECT_ROOT, logger
from app.infra.config.providers import settings
from app.process.query.agent.main_graph import query_graph_app
from app.process.query.agent.state import create_query_default_state, QueryGraphState
from app.shared.utils.sse_utils import SSEEvent, create_sse_queue, push_to_session, sse_generator
from app.shared.utils.task_utils import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PROCESSING,
    clear_task,
    get_done_task_list,
    get_task_result,
    update_task_status,
)

# 定义fastapi对象
app = FastAPI(
    title=settings.query_app_name,
    description="描述,进行rag查询的服务对象",
    version="0.2.0"
)

# 跨域处理
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*']
)


# 1 html
@app.get('/html')
def chat_html():
    chat_html_path_obj = PROJECT_ROOT / 'app' / 'resources' / 'html' / 'chat.html'
    return FileResponse(
        path=chat_html_path_obj,
        media_type=guess_type(chat_html_path_obj.name)[0]
    )


# 2 health
@app.get('/health')
def health():
    return {'alive': 'yes'}


# 3 SSE
@app.get('/stream/{session_id}')
def stream(session_id: str, request: Request):
    return StreamingResponse(
        sse_generator(session_id, request),
        media_type='text/event-stream'
    )


# 4 query
def invoke_query_graph(session_id: str, query: str, is_stream: bool = False)->QueryGraphState:
    state = create_query_default_state(
        session_id=session_id,
        original_query=query,
        is_stream=is_stream
    )
    clear_task(session_id)
    if is_stream:
        # 创建队列
        create_sse_queue(session_id)
    try:
        update_task_status(session_id, TASK_STATUS_PROCESSING, is_stream)
        logger.info(f'{session_id}开始执行,开始状态为{state}')
        result_state:QueryGraphState = query_graph_app.invoke(state)
        logger.info(f'{session_id}执行完毕,结果为:{result_state}')
        update_task_status(session_id, TASK_STATUS_COMPLETED, is_stream)

        if is_stream:
            push_to_session(
                session_id,
                SSEEvent.FINAL,
                {
                    "answer": result_state.get('answer'),
                    "status": "completed",
                    "image_urls": result_state.get('image_urls',[])
                }
            )
            logger.info(f"流式输出完成，总长度: {len(result_state.get('answer'))}")
        return result_state
    except Exception as e:
        update_task_status(session_id, TASK_STATUS_FAILED, is_stream)
        push_to_session(session_id, SSEEvent.ERROR, {"error": str(e)})
        logger.exception(f'{session_id}问题解析失败')


@app.post('/query')
def query(background_tasks: BackgroundTasks, request: QueryRequestSchema):
    session_id = request.session_id or str(uuid.uuid4())
    query = request.query
    is_stream = request.is_stream

    if is_stream:

        background_tasks.add_task(
            invoke_query_graph,
            session_id=session_id,
            query=query,
            is_stream=is_stream
        )
        return QueryStreamResponseSchema(
            message=f'结果正在处理中',
            session_id=session_id
        )
    else:
        result_state: QueryGraphState = invoke_query_graph(session_id, query, is_stream)

        return QueryResponseSchema(
            message=f'{session_id}处理完成',
            session_id=session_id,
            answer=result_state.get('answer'),
            done_list=get_done_task_list(session_id),
            image_urls=result_state.get('image_urls')
        )


@app.get('/history/{session_id}', response_model=HistoryResponseSchema)
def history(session_id: str, limit: int = 10):
    records = history_repository.list_recent(session_id=session_id, limit=limit)
    items = [
        HistoryItemSchema(
            id=str(record.get('_id')) if record.get('_id') else '',
            session_id=record.get('session_id', ''),
            role=record.get('role', ''),
            text=record.get('text', ''),
            rewritten_query=record.get('rewritten_query', ''),
            item_names=record.get('item_names', []),
            image_urls=record.get('image_urls', []),
            ts=record.get('ts'),
        )
        for record in records
    ]
    return HistoryResponseSchema(session_id=session_id, items=items)


@app.delete('/history/{session_id}')
def clear_history(session_id: str):
    delete_count = history_repository.clear_session(session_id=session_id)
    return ClearHistoryResponseSchema(
        message=f'删除:{session_id}会话对应的聊天记录成功！！',
        deleted_count=delete_count
    )


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host=settings.app_host, port=settings.query_app_port)
