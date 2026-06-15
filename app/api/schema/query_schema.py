from typing import Any

from pydantic import BaseModel

class QueryRequestParam(BaseModel):
    query:str
    session_id:str
    user_id: str | None = None
    is_stream:bool=False
    selected_subject: str | None = None

class QueryStreamResponse(BaseModel):
    message:str
    session_id:str

class QueryNotStreamResponse(BaseModel):
    message: str
    session_id: str
    answer:str
    done_list:list
    image_urls:list

class InterruptInfo(BaseModel):
    title: str
    description: str
    options: list[str]
    type: str

class InterruptResponse(BaseModel):
    message: str
    session_id: str
    status: str
    interrupt: InterruptInfo

class InterruptResumeParam(BaseModel):
    session_id: str
    selected_value: str
    query: str | None = None
    is_stream: bool = False

class HistoryCleanResponse(BaseModel):
    message:str
    deleted_count:int

class HistoryItemResponse(BaseModel):
    id:str
    session_id:str
    role:str
    text:str
    rewritten_query:str
    item_names:list
    image_urls:list | None
    ts:Any

class HistoryResponse(BaseModel):
    session_id:str
    items:list[HistoryItemResponse]


