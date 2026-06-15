"""
导入服务 Pydantic 模型定义
定义文件上传、任务状态查询等接口的响应体结构
对应接口设计文档中的导入相关数据模型
"""
from pydantic import BaseModel


class UploadResponse(BaseModel):
    """文件上传响应体：返回状态码、提示信息、任务 ID 列表"""
    code: int = 200
    message: str = "上传成功"
    task_ids: list[str] = []


class TaskStatusResponse(BaseModel):
    """任务状态查询响应体：返回任务进度、已完成/运行中节点列表"""
    code: int = 200
    task_id: str
    status: str  # pending / processing / completed / failed
    done_list: list[str] = []
    running_list: list[str] = []
    progress: float = 0.0
