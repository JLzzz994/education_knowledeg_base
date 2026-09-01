"""
导入服务 Pydantic 模型定义
定义文件上传、任务状态查询等接口的响应体结构
"""
from pydantic import BaseModel


class UploadResponse(BaseModel):
    """文件上传响应 — 返回任务 ID 列表"""
    code: int = 200
    message: str = "上传成功"
    task_ids: list[str] = []


class TaskStatusResponse(BaseModel):
    """任务状态查询响应 — 返回进度和节点列表（REQ-05 权重进度）"""
    code: int = 200
    task_id: str
    status: str
    progress: int = 0  # REQ-05: 权重进度百分比 0-100
    done_list: list[str] = []
    running_list: list[str] = []
