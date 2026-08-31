"""
导入服务 HTTP 入口模块，直接承载导入接口与相关接口业务逻辑。
"""
import shutil
import sys
import uuid
from datetime import datetime
from mimetypes import guess_type
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, UploadFile
from fastapi.responses import FileResponse
from starlette.middleware.cors import CORSMiddleware

from app.api.schema.import_schema import TaskStatusSchema, UploadSchema
from app.shared.runtime.logger import PROJECT_ROOT, logger
from app.process.import_.agent.main_graph import graph
from app.process.import_.agent.state import get_default_state, ImportGraphState, create_default_state
from app.infra.config.providers import settings
from app.shared.utils.task_utils import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PROCESSING,
    get_done_task_list,
    get_running_task_list,
    get_task_status,
    update_task_status, add_running_task, add_done_task,
)
app = FastAPI(
    title=settings.import_app_name,
    description='企业化 RAG 导入服务,负责文件上传、导入执行与状态查询。',
    version='0.2.0',
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins) or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1 返回import.html文件
@app.get("/html")
def html():
    html_path_obj = PROJECT_ROOT / 'app' / 'resources' / 'html' / 'import.html'
    return FileResponse(
        path=html_path_obj,
        media_type=guess_type(html_path_obj.name)[0]
    )

# 2 # 返回task_id 对应的任务状态
@app.get("/status/{task_id}")
def task_status(task_id: str):
    logger.info(f'获取任务状态接口被调用task_id:{task_id}')
    return TaskStatusSchema(
        code=200,
        task_id=task_id,
        status=get_task_status(task_id),
        done_list=get_done_task_list(task_id),
        running_list=get_running_task_list(task_id),
    )

# 3 上传文件
def invoke_graph(task_id: str, local_file_path: str, local_dir: str):
    '''
    调用图对象
    :param task_id:
    :param local_file_path:
    :param local_dir:
    :return:
    '''
    state = create_default_state(task_id=task_id,local_file_path=local_file_path,local_dir=local_dir)
    try:
        logger.info(f"{task_id}对应的文件解析任务开始执行！参数state:{state}")
        update_task_status(task_id,TASK_STATUS_PROCESSING)
        final_state = graph.invoke(state)
        logger.info(f'{task_id}对应的文件解析任务完成！最终结果为:{final_state.get("item_name")}')
        update_task_status(task_id,TASK_STATUS_COMPLETED)
    except Exception as e:
        update_task_status(task_id,TASK_STATUS_FAILED)
        logger.exception(f'==========全流程测试运行失败==========')
@app.post("/upload")
def upload_and_invoke_graph(background_tasks:BackgroundTasks,files: list[UploadFile]=File(...)):
    '''
    1接收上传文件存储 2异步执行导入图对象 state local_file_dir local_dir task_id 3返回结果
    :param background_tasks:
    :param files:
    :return:
    '''
    # 1 接收上传文件存储(文件存储到项目目录下)
    # 存储位置 / output / 时间 / task_id / local_dir  +  文件名 local_file_path
    task_id = str(uuid.uuid4())
    local_dir_obj = PROJECT_ROOT / 'output' / datetime.now().strftime("%Y%m%d") / task_id
    local_dir_obj.mkdir(parents=True,exist_ok=True)

    # 1.1 存储数据
    current_file = files[0]
    local_file_path_dir:Path = local_dir_obj / current_file.filename

    with local_file_path_dir.open('wb') as file_buffer:
        shutil.copyfileobj(current_file.file,file_buffer)

    # 2 异步调用
    background_tasks.add_task(
        invoke_graph,
        task_id=task_id,
        local_file_path=str(local_file_path_dir),
        local_dir=str(local_dir_obj)
    )
    # 3 返回结果
    return UploadSchema(
        code=200,
        message='上传成功',
        task_ids=[task_id]

    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.app_host, port=settings.import_app_port)