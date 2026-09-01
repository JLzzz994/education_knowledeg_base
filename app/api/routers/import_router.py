"""
导入服务路由模块
实现文件上传、任务状态查询等接口

接口清单:
  POST /upload          — 上传文件（需 admin 或 whitelist 角色）
  GET  /status/{task_id} — 查询导入任务进度（无需认证）
"""
import os
import uuid
import shutil
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.api.schemas.import_schema import UploadResponse, TaskStatusResponse
from app.api.routers.auth_router import get_current_user
from app.process.import_.agent.main_graph import import_graph_app
from app.process.import_.agent.state import create_default_state
from app.shared.runtime.logger import PROJECT_ROOT, logger
from app.shared.utils.task_utils import (
    update_task_status,
    get_task_status,
    get_done_task_list,
    get_running_task_list,
    add_running_task,
    add_done_task,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
)

router = APIRouter()


# ==================== 导入权限校验 ====================

def require_import_permission(user: dict = Depends(get_current_user)) -> dict:
    """
    导入权限依赖：校验当前用户是否为 admin 或 whitelist 角色
    权限矩阵:
      admin     → 全部权限
      whitelist → 可导入文件
      user      → 仅查询（无导入权限）
    """
    if user.get("role") not in ("admin", "whitelist"):
        raise HTTPException(status_code=403, detail="无导入权限")
    return user


# ==================== 后台任务执行 ====================

def _run_import_task(task_id: str, file_path: str, output_dir: str):
    """
    后台执行导入图流程（由 FastAPI BackgroundTasks 在线程池中调用）
    流程:
      1. 更新任务状态为 processing
      2. 构造 LangGraph 初始状态
      3. 同步调用 graph.invoke(state) 执行导入图
      4. 完成/失败后更新任务状态
    """
    try:
        update_task_status(task_id, TASK_STATUS_PROCESSING)
        state = create_default_state(
            task_id=task_id,
            local_file_path=file_path,
            local_dir=output_dir,
        )
        logger.info(f"导入任务开始: {task_id}")
        final_state = import_graph_app.invoke(state)
        update_task_status(task_id, TASK_STATUS_COMPLETED)
        logger.info(f"导入任务完成: {task_id}, 结果: {final_state.get('item_name')}")
    except Exception as e:
        update_task_status(task_id, TASK_STATUS_FAILED)
        logger.exception(f"导入任务失败: {task_id}")


# ==================== 导入接口 ====================

@router.post("/upload", response_model=UploadResponse)
async def upload_files(
        background_tasks: BackgroundTasks,
        files: list[UploadFile] = File(...),
        user: dict = Depends(require_import_permission),
):
    """
    文件上传接口
    流程:
      1. 生成唯一 task_id
      2. 保存文件到 output/{YYYYMMDD}/{task_id}/ 目录
      3. 初始化任务状态
      4. 后台异步触发导入图流程
      5. 立即返回 task_id
    """
    task_id = str(uuid.uuid4())
    add_running_task(task_id, "upload_file")

    # 1. 创建输出目录
    today = datetime.now().strftime("%Y%m%d")
    output_dir = os.path.join(str(PROJECT_ROOT), "output", today, task_id)
    os.makedirs(output_dir, exist_ok=True)

    # 2. 保存上传文件
    cur_file = files[0]
    file_path = os.path.join(output_dir, cur_file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(cur_file.file, f)

    add_done_task(task_id, "upload_file")
    logger.info(f"文件上传成功: {cur_file.filename} -> task_id={task_id}")

    # 3. 后台异步执行导入流程
    background_tasks.add_task(_run_import_task, task_id, file_path, output_dir)

    return UploadResponse(code=200, message="上传成功", task_ids=[task_id])


@router.get("/status/{task_id}", response_model=TaskStatusResponse)
def get_task_progress(task_id: str):
    """
    任务状态查询接口（无需认证）
    返回任务当前状态、已完成节点、运行中节点
    """
    status = get_task_status(task_id)
    if not status:
        return JSONResponse(
            status_code=404,
            content={"code": 404, "task_id": task_id, "status": "not_found",
                     "done_list": [], "running_list": [],
                     "message": f"任务 {task_id} 不存在"},
        )

    return TaskStatusResponse(
        code=200,
        task_id=task_id,
        status=status,
        done_list=get_done_task_list(task_id),
        running_list=get_running_task_list(task_id),
    )
