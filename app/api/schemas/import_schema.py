from pydantic import BaseModel


# 上传文件的相应数据类型
class UploadSchema(BaseModel):
    code: int = 200
    message: str
    task_ids: list[str]


# 查询任务状态的数据类型
class TaskStatusSchema(BaseModel):
    code: int = 200
    task_id: str
    status: str # processing / completed / failed
    done_list: list[str] # 可能有多个
    running_list: list[str] # 只有一个
