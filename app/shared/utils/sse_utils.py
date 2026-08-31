"""
SSE（Server-Sent Events）工具模块
提供基于 queue.Queue 的 SSE 会话队列管理，支持实时推送任务进度和 LLM 流式输出

使用流程:
1. 前端建立 SSE 连接时，调用 create_sse_queue(session_id) 创建队列
2. 后端任务执行中，调用 push_to_session(session_id, event, data) 推送事件
3. sse_generator() 作为 FastAPI StreamingResponse 的生成器，持续读取队列并输出 SSE 流
4. 连接断开时自动清理队列资源
"""
import json
import queue
import asyncio
from typing import Dict, Any, Optional, AsyncGenerator
from fastapi import Request

from app.shared.runtime.logger import logger


# ==================== SSE 事件类型常量 ====================
class SSEEvent:
    """SSE 事件类型枚举，对应前端 onmessage 的 event 字段"""
    READY = "ready"         # 连接建立信号
    PROGRESS = "progress"   # 任务节点进度（状态/已完成/进行中）
    DELTA = "delta"         # LLM 流式输出增量（逐 token）
    FINAL = "final"         # 最终完整答案
    ERROR = "error"         # 错误信息
    INTERRUPT = "interrupt" # 中断请求，需要用户输入
    SEARCH_MODE = "search_mode"  # REQ-12: 网络检索提示（无主体时走纯网搜）
    CLOSE = "__close__"     # 关闭连接信号


# ==================== 全局会话队列存储 ====================
# key: session_id（任务 ID 或会话 ID）
# value: queue.Queue（线程安全队列，存放待推送的事件）
_session_stream: Dict[str, queue.Queue] = {}


def get_sse_queue(session_id: str) -> Optional["queue.Queue"]:
    """获取指定 session 的队列，不存在返回 None"""
    return _session_stream.get(session_id)


def create_sse_queue(session_id: str) -> "queue.Queue":
    """
    创建并注册一个新的 SSE 队列
    在前端建立 SSE 连接时调用，为该 session 分配独立的消息队列
    """
    logger.info(f"[SSE] Creating queue for session: {session_id}")
    q = queue.Queue()
    _session_stream[session_id] = q
    return q


def remove_sse_queue(session_id: str):
    """
    移除指定 session 的队列
    在 SSE 连接断开时调用，释放内存资源
    """
    logger.info(f"[SSE] Removing queue for session: {session_id}")
    _session_stream.pop(session_id, None)


def _sse_pack(event: str, data: Dict[str, Any]) -> str:
    """
    打包 SSE 消息格式
    遵循 SSE 协议: event: {event}\ndata: {json}\n\n
    """
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def push_to_session(session_id: str, event: str, data: Dict[str, Any]):
    """
    向指定 session 推送事件（线程安全）
    由后台任务线程调用，将事件放入队列等待 SSE 生成器消费
    :param session_id: 会话 ID
    :param event: 事件类型（如 "progress", "delta", "final"）
    :param data: 事件数据字典
    """
    stream_queue = get_sse_queue(session_id)
    if stream_queue:
        stream_queue.put({"event": event, "data": data})
    else:
        logger.warning(f"[SSE] No queue found for session {session_id} when pushing {event}")


async def sse_generator(session_id: str, request: Request):
    """
    SSE 异步生成器，供 FastAPI StreamingResponse 使用
    1. 发送 ready 信号确认连接建立
    2. 循环从队列读取事件并 yield 给客户端
    3. 收到 __close__ 信号或客户端断开时退出
    4. finally 中清理队列资源
    :param session_id: 会话 ID
    :param request: FastAPI Request 对象（用于检测客户端断开）
    """
    logger.info(f"[SSE] Generator started for session: {session_id}")
    stream_queue = get_sse_queue(session_id)
    if stream_queue is None:
        logger.error(f"[SSE] Queue not found for session {session_id}. Available sessions: {list(_session_stream.keys())}")
        return

    loop = asyncio.get_running_loop()
    try:
        # 1. 发送连接建立信号
        logger.info(f"[SSE] Sending ready signal for {session_id}")
        yield _sse_pack("ready", {})

        # 2. 持续消费队列中的事件
        while True:
            # 检测客户端是否断开
            if await request.is_disconnected():
                logger.info(f"[SSE] Client disconnected: {session_id}")
                break

            try:
                # 使用 run_in_executor 将阻塞的 queue.get 放到线程池执行
                # 超时 1 秒，避免永久阻塞导致无法检测客户端断开
                msg = await loop.run_in_executor(None, stream_queue.get, True, 1.0)
            except queue.Empty:
                # 队列为空，继续等待
                continue

            event = msg.get("event")
            data = msg.get("data")

            # 3. 收到关闭信号，退出循环
            if event == "__close__":
                logger.info(f"[SSE] Closing signal received for {session_id}")
                break

            # 4. 正常推送事件
            yield _sse_pack(event, data)

    except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
        # 客户端强制断开（取消/重置/管道破裂），静默退出
        logger.info(f"[SSE] Client disconnected (Cancelled/Reset/Pipe): {session_id}")
        return
    except Exception as e:
        logger.error(f"[SSE] Exception in generator for {session_id}: {e}")
    finally:
        # 5. 清理资源，移除队列释放内存
        logger.info(f"[SSE] Generator finished for {session_id}")
        remove_sse_queue(session_id)