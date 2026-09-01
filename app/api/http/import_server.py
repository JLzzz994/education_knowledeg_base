"""
导入服务 HTTP 入口模块，直接承载导入接口与相关接口业务逻辑。
"""
import shutil
import sys
import uuid
from datetime import datetime
from mimetypes import guess_type
from pathlib import Path

from app.api.schemas.import_schema import TaskStatusResponse, UploadResponse
from app.api.routers.auth_router import get_current_user

# 兼容直接以 `python import_server.py` 方式启动，提前把项目根目录加入模块搜索路径。
if __package__ in (None, ""):
    bootstrap_root = Path(__file__).resolve().parents[3]
    if str(bootstrap_root) not in sys.path:
        sys.path.insert(0, str(bootstrap_root))

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.middleware.cors import CORSMiddleware


from app.shared.runtime.logger import PROJECT_ROOT, logger
from app.process.import_.agent.main_graph import import_graph_app
from app.process.import_.agent.state import create_default_state
from app.infra.config.providers import settings
from app.shared.utils.task_utils import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PROCESSING,
    get_done_task_list,
    get_running_task_list,
    get_task_progress,
    get_task_status,
    update_task_status, add_done_task, add_running_task,
)
app = FastAPI(
    title=settings.import_app_name,
    description="企业化 RAG 导入服务，负责文件上传、导入执行与状态查询。",
    version="0.2.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins) or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


# 1 展示页面
@app.get("/html")
def html():
    html_path_obj = PROJECT_ROOT / 'app' / 'resources' / 'html' / 'import.html'
    return FileResponse(
        path=html_path_obj,
        media_type=guess_type(html_path_obj.name)[0]
    )

# 2 获取任务状态（REQ-05: 包含权重进度）
@app.get('/status/{task_id}')
def task_status(task_id: str):
    status = get_task_status(task_id)
    done = get_done_task_list(task_id)
    running = get_running_task_list(task_id)
    progress = get_task_progress(task_id)
    logger.info(f'[STATUS] task_id={task_id} status={status} progress={progress} done={done} running={running}')
    return TaskStatusResponse(
        code=200,
        task_id=task_id,
        status=status,
        progress=progress,
        done_list=done,
        running_list=running
    )

# 3 upload
def invoke_graph(task_id, local_dir, local_file_path):
    state = create_default_state(task_id=task_id, local_file_path=local_file_path, local_dir=local_dir)
    try:
        logger.info(f"{task_id}对应的文件解析任务开始执行! 参数state:{state}")
        update_task_status(task_id, TASK_STATUS_PROCESSING)
        final_state = import_graph_app.invoke(state)
        update_task_status(task_id, TASK_STATUS_COMPLETED)
        logger.info(f"{task_id}对应的文件解析任务完成! 最终结果为:{final_state.get('item_name')}")
    except Exception as e:
        update_task_status(task_id, TASK_STATUS_FAILED)
        logger.exception(f"===== 全流程测试运行失败 =====")


@app.post('/upload')
def upload_and_invoke_graph(background_tasks: BackgroundTasks, files: list[UploadFile] = File(...),
                           user: dict = Depends(require_import_permission)):
    """
    REQ-11: 支持多文件同时上传，每个文件独立 task_id，并行处理
    """
    task_ids = []
    for cur_file in files:
        task_id = str(uuid.uuid4())
        task_ids.append(task_id)
        add_running_task(task_id, 'upload_file')
        local_dir_obj = PROJECT_ROOT / 'output' / datetime.now().strftime('%Y%m%d') / task_id
        local_dir_obj.mkdir(parents=True, exist_ok=True)
        local_file_path_obj = local_dir_obj / cur_file.filename
        with local_file_path_obj.open('wb') as file_buffer:
            shutil.copyfileobj(cur_file.file, file_buffer)
        add_done_task(task_id, 'upload_file')

        # 每个文件独立调用 graph
        background_tasks.add_task(
            invoke_graph,
            task_id=task_id,
            local_dir=str(local_dir_obj),
            local_file_path=str(local_file_path_obj)
        )

    return UploadResponse(
        code=200,
        message='上传成功',
        task_ids=task_ids,
    )
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=settings.app_host, port=settings.import_app_port)