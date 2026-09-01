from mimetypes import guess_type
from pathlib import Path
import sys
import uuid

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from langgraph.errors import GraphInterrupt

from app.api.schemas.query_schema import (
    QueryRequestParam, QueryNotStreamResponse, QueryStreamResponse,
    HistoryCleanResponse, HistoryItemResponse, HistoryResponse,
    InterruptResumeParam, SessionItemResponse, SessionListResponse,
    UserHistoryResponse,
)
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
    add_done_task,
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


# 1 返回页面
@app.get('/html')
def chat_html():
    chat_html_path_obj = PROJECT_ROOT / 'app' / 'resources' / 'html' / 'chat.html'
    return FileResponse(
        path=chat_html_path_obj,
        media_type=guess_type(chat_html_path_obj.name)[0]
    )


@app.get('/app')
def app_html():
    """合并后的单页应用（问答+导入）"""
    app_html_path_obj = PROJECT_ROOT / 'app' / 'resources' / 'html' / 'app.html'
    return FileResponse(
        path=app_html_path_obj,
        media_type=guess_type(app_html_path_obj.name)[0]
    )


# 2 SSE 推送接口
@app.get('/stream/{session_id}')
def stream(session_id: str, request: Request):
    return StreamingResponse(
        sse_generator(session_id, request),
        media_type='text/event-stream'
    )


# 3 健康检查
@app.get('/health')
def health():
    return {'check': 'ok'}


# 4 查询和提问接口
def invoke_query_graph(session_id: str, query: str, is_stream: bool, user_id: str = ''):
    '''
    调用图
    :param session_id:
    :param query:
    :param is_stream:
    :return:
    '''
    state = create_query_default_state(
        session_id=session_id,
        original_query=query,
        is_stream=is_stream,
        user_id=user_id,
    )
    # 清空task_utils数据
    clear_task(session_id)
    config = {"configurable": {"thread_id": session_id}}
    result_state = None
    try:
        update_task_status(session_id, TASK_STATUS_PROCESSING, is_stream)
        logger.info(f'开始执行:执行参数为:{state}')
        result_state = query_graph_app.invoke(state, config=config)
        logger.info(f'执行结束,执行结果是:{result_state}')
        update_task_status(session_id, TASK_STATUS_COMPLETED, is_stream)
        if is_stream:
            push_to_session(
                session_id,
                SSEEvent.FINAL,
                {
                    "answer": result_state.get("answer"),
                    "status": "completed",
                    "image_urls": result_state.get("image_urls", [])
                }
            )
            logger.info(f"流式输出完成，总长度: {len(result_state.get('answer', ''))}")
    except GraphInterrupt as e:
        # LangGraph 中断：需要用户选择主体名称
        # GraphInterrupt 包含 Interrupt 对象元组，取第一个的 value
        interrupt_value = e.args[0][0].value if e.args and e.args[0] else {}
        logger.info(f'{session_id} 图中断，等待用户选择: {interrupt_value}')
        # 中断时 node_item_name_confirm 的 add_done_task 未执行，需手动补上
        add_done_task(session_id, "node_item_name_confirm", is_stream)
        update_task_status(session_id, TASK_STATUS_COMPLETED, is_stream)
        if is_stream:
            push_to_session(
                session_id,
                SSEEvent.INTERRUPT,
                {
                    "interrupt": interrupt_value,
                    "session_id": session_id,
                }
            )
        else:
            # 非流式：将中断数据存入 task result，供同步响应返回
            from app.shared.utils.task_utils import set_task_result
            import json as _json
            set_task_result(session_id, "interrupt", _json.dumps(interrupt_value, ensure_ascii=False))
    except Exception as e:
        update_task_status(session_id, TASK_STATUS_FAILED, is_stream)
        push_to_session(session_id, SSEEvent.ERROR, {"error": str(e)})
        logger.exception(f'{session_id}执行出现异常!')
    return result_state


@app.post('/resume')
def resume_graph(backgroundtasks: BackgroundTasks, request: InterruptResumeParam):
    """
    恢复中断的图执行
    当 LangGraph 触发 interrupt（如主体名确认）时，用户选择后调用此接口继续执行
    """
    session_id = request.session_id
    selected_value = request.selected_value
    is_stream = request.is_stream

    if is_stream:
        create_sse_queue(session_id)
        backgroundtasks.add_task(
            _resume_graph_task,
            session_id=session_id,
            selected_value=selected_value,
            is_stream=is_stream
        )
        return {"message": f"恢复执行: {session_id}", "session_id": session_id}
    else:
        result_state = _resume_graph_task(session_id, selected_value, is_stream)
        return {
            "message": f"{session_id} 恢复执行完成",
            "session_id": session_id,
            "answer": result_state.get("answer") if result_state else "执行失败",
            "image_urls": result_state.get("image_urls", []) if result_state else [],
        }


def _resume_graph_task(session_id: str, selected_value: str, is_stream: bool):
    """
    后台恢复图执行
    1. 使用 graph.invoke(None, config) 从检查点恢复
    2. 将用户选择的值传给图
    """
    config = {"configurable": {"thread_id": session_id}}
    result_state = None
    try:
        update_task_status(session_id, TASK_STATUS_PROCESSING, is_stream)
        logger.info(f'{session_id} 恢复执行，用户选择: {selected_value}')
        # 从检查点恢复，传入用户选择的值
        result_state = query_graph_app.invoke(selected_value, config=config)
        logger.info(f'{session_id} 恢复执行完成: {result_state}')
        update_task_status(session_id, TASK_STATUS_COMPLETED, is_stream)
        if is_stream:
            push_to_session(
                session_id,
                SSEEvent.FINAL,
                {
                    "answer": result_state.get("answer"),
                    "status": "completed",
                    "image_urls": result_state.get("image_urls", [])
                }
            )
    except GraphInterrupt as e:
        # 再次中断（理论上不应该发生）
        interrupt_value = e.args[0][0].value if e.args and e.args[0] else {}
        logger.warning(f'{session_id} 恢复执行后再次中断: {interrupt_value}')
        add_done_task(session_id, "node_item_name_confirm", is_stream)
        update_task_status(session_id, TASK_STATUS_COMPLETED, is_stream)
        if is_stream:
            push_to_session(
                session_id,
                SSEEvent.INTERRUPT,
                {
                    "interrupt": interrupt_value,
                    "session_id": session_id,
                }
            )
    except Exception as e:
        update_task_status(session_id, TASK_STATUS_FAILED, is_stream)
        push_to_session(session_id, SSEEvent.ERROR, {"error": str(e)})
        logger.exception(f'{session_id} 恢复执行失败!')
    return result_state


@app.post('/query')
def query(backgroundtasks: BackgroundTasks, request: QueryRequestParam):
    '''
    1 获取stream状态
    2 true 异步 后台执行 通过backgroundtasks调用图
    异步的返回结果
    3 false 同步 直接调用
    同步的返回结果

    :param backgroundtasks:
    :param request:
    :return:
    '''
    session_id = request.session_id or str(uuid.uuid4())
    is_stream = request.is_stream
    query = request.query
    user_id = request.user_id or ''

    if is_stream:
        # 先创建 SSE 队列，确保前端 EventSource 连接时队列已存在
        create_sse_queue(session_id)
        backgroundtasks.add_task(
            invoke_query_graph,
            session_id=session_id,
            query=query,
            is_stream=is_stream,
            user_id=user_id,
        )
        return QueryStreamResponse(
            message=f'开启:{session_id}异步执行任务',
            session_id=session_id
        )
    else:
        # 同步执行 死等
        final_state = invoke_query_graph(session_id=session_id, query=query, is_stream=is_stream, user_id=user_id)

        # 检查是否有中断数据（需用户选择主体）
        interrupt_data = None
        interrupt_raw = get_task_result(session_id, "interrupt")
        if interrupt_raw:
            import json as _json
            try:
                interrupt_data = _json.loads(interrupt_raw)
            except Exception:
                interrupt_data = None

        if final_state is None and not interrupt_data:
            return QueryNotStreamResponse(
                message=f'{session_id}执行失败',
                session_id=session_id,
                answer='执行出现异常，请查看日志',
                done_list=get_done_task_list(session_id),
                image_urls=[]
            )
        return QueryNotStreamResponse(
            message=f'{session_id}对应的任务已经处理完毕！！',
            session_id=session_id,
            answer=final_state.get('answer', '') if final_state else '',
            done_list=get_done_task_list(session_id),
            image_urls=final_state.get('image_urls', []) if final_state else [],
            interrupt=interrupt_data
        )


@app.delete("/history/{session_id}")
def clear_history(session_id: str):
    delete_count = history_repository.clear_history(session_id=session_id)
    return HistoryCleanResponse(
        message=f'删除{session_id}回话对应的链条记录成功',
        deleted_count=delete_count
    )


@app.get("/history/{session_id}")
def list_recent_history(session_id: str, limit: int = 10):
    records = history_repository.list_recent(session_id=session_id, limit=limit)
    items = [
        HistoryItemResponse(
            id=str(record.get('_id')),
            session_id=record.get('session_id'),
            role=record.get('role'),
            text=record.get('text'),
            rewritten_query=record.get('rewritten_query'),
            item_names=record.get('item_names'),
            image_urls=record.get('image_urls'),
            ts=record.get('ts')
        )
        for record in records
    ]
    return HistoryResponse(
        session_id=session_id,
        items=items
    )


# ==================== REQ-07: 用户维度查询 ====================

@app.get("/sessions/{user_id}")
def list_user_sessions(user_id: str, limit: int = 20):
    """获取用户的会话列表（REQ-07）"""
    sessions = history_repository.list_user_sessions(user_id, limit)
    items = [
        SessionItemResponse(
            session_id=s.get('session_id'),
            last_active=s.get('last_active'),
            message_count=s.get('message_count', 0),
            last_query=s.get('last_query', ''),
            item_names=s.get('item_names', []),
        )
        for s in sessions
    ]
    return SessionListResponse(user_id=user_id, sessions=items)


@app.get("/history/user/{user_id}")
def list_user_history(user_id: str, page: int = 1, page_size: int = 50):
    """获取用户的历史消息（分页，REQ-07）"""
    records, total = history_repository.list_user_history(user_id, page=page, page_size=page_size)
    items = [
        HistoryItemResponse(
            id=str(record.get('_id')),
            session_id=record.get('session_id'),
            role=record.get('role'),
            text=record.get('text'),
            rewritten_query=record.get('rewritten_query'),
            item_names=record.get('item_names'),
            image_urls=record.get('image_urls'),
            ts=record.get('ts')
        )
        for record in records
    ]
    return UserHistoryResponse(user_id=user_id, total=total, items=items)


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host=settings.app_host, port=settings.query_app_port)
