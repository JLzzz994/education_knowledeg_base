"""
导入服务路由模块
实现文件上传、任务状态查询等接口
遵循接口设计文档中的请求/响应格式
REQ-04: /upload 端点需要 admin 或 whitelist 角色才能访问
"""
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.api.schemas.import_schema import UploadResponse, TaskStatusResponse
from app.api.routers.auth_router import get_current_user
from app.process.import_.agent.main_graph import import_graph_app
from app.process.import_.agent.state import create_default_state
from app.rag.import_.config import NODE_WEIGHTS
from app.shared.runtime.logger import logger
from app.shared.utils.path_util import PROJECT_ROOT
from app.shared.utils.task_utils import (
    update_task_status,
    get_task_status,
    get_done_task_list,
    get_running_task_list,
    add_running_task,
    add_done_task,
    TASK_STATUS_PENDING,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
)

router = APIRouter()


# ==================== 导入权限校验 ====================

def require_import_permission(user: dict = Depends(get_current_user)) -> dict:
    """
    导入权限依赖：校验当前用户是否为 admin 或 whitelist 角色
    权限矩阵: admin → 全部权限, whitelist → 可导入, user → 仅查询
    :param user: 当前用户信息（由 get_current_user 提供）
    :return: 用户信息字典
    :raises HTTPException: 角色不满足时返回 403
    """
    if user.get("role") not in ("admin", "whitelist"):
        raise HTTPException(status_code=403, detail="无导入权限")
    return user


def _calc_progress(task_id: str) -> float:
    """
    根据已完成节点的权重计算整体进度百分比
    :param task_id: 任务 ID
    :return: 0.0 ~ 100.0 的进度值
    """
    done_list = get_done_task_list(task_id)
    # done_list 返回的是中文名，需要反查英文节点名
    # 构建 中文名 -> 节点名 的反向映射
    from app.shared.utils.task_utils import _NODE_NAME_TO_CN
    cn_to_node = {v: k for k, v in _NODE_NAME_TO_CN.items()}

    total_weight = sum(NODE_WEIGHTS.values())
    done_weight = 0
    for cn_name in done_list:
        node_name = cn_to_node.get(cn_name, "")
        done_weight += NODE_WEIGHTS.get(node_name, 0)

    return round(done_weight / total_weight * 100, 1) if total_weight > 0 else 0.0


def _run_import_task(task_id: str, file_path: str, output_dir: str):
    """
    后台执行导入图流程（由 BackgroundTasks 调用）
    :param task_id: 任务 ID
    :param file_path: 上传文件的本地路径
    :param output_dir: 中间文件输出目录
    """
    try:
        # 1. 更新任务状态为 processing
        update_task_status(task_id, TASK_STATUS_PROCESSING)

        # 2. 构造初始状态
        state = create_default_state(
            task_id=task_id,
            local_file_path=file_path,
            local_dir=output_dir,
        )

        # 3. 执行导入图（同步调用，运行在后台线程）
        import_graph_app.invoke(state)

        # 4. 执行完成
        update_task_status(task_id, TASK_STATUS_COMPLETED)
        logger.info(f"导入任务完成: {task_id}")

    except Exception as e:
        update_task_status(task_id, TASK_STATUS_FAILED)
        logger.exception(f"导入任务失败: {task_id}, 错误: {e}")


# ==================== 导入接口 ====================

@router.post("/upload", response_model=UploadResponse)
async def upload_files(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    user: dict = Depends(require_import_permission),
):
    """
    文件上传接口
    1. 为每个文件生成唯一 task_id
    2. 保存文件到 output/{YYYYMMDD}/{task_id}/ 目录
    3. 后台异步触发导入图流程
    4. 立即返回 task_ids 列表
    """
    task_ids = []
    today = datetime.now().strftime("%Y%m%d")

    for file in files:
        # 1. 生成 task_id 和输出目录
        task_id = str(uuid.uuid4())
        output_dir = os.path.join(PROJECT_ROOT, "output", today, task_id)
        os.makedirs(output_dir, exist_ok=True)

        # 2. 保存上传文件到本地
        file_path = os.path.join(output_dir, file.filename)
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        # 3. 初始化任务状态
        update_task_status(task_id, TASK_STATUS_PENDING)

        # 4. 后台异步执行导入流程
        background_tasks.add_task(_run_import_task, task_id, file_path, output_dir)

        task_ids.append(task_id)
        logger.info(f"文件上传成功: {file.filename} -> task_id={task_id}")

    return UploadResponse(code=200, message="上传成功", task_ids=task_ids)


@router.get("/status/{task_id}", response_model=TaskStatusResponse)
def get_task_progress(task_id: str):
    """
    任务状态查询接口
    返回任务当前状态、已完成节点、运行中节点、整体进度百分比
    """
    status = get_task_status(task_id)

    # 任务不存在时返回 404
    if not status:
        return JSONResponse(
            status_code=404,
            content={"code": 404, "message": f"任务 {task_id} 不存在"},
        )

    done_list = get_done_task_list(task_id)
    running_list = get_running_task_list(task_id)
    progress = _calc_progress(task_id)

    return TaskStatusResponse(
        code=200,
        task_id=task_id,
        status=status,
        done_list=done_list,
        running_list=running_list,
        progress=progress,
    )
