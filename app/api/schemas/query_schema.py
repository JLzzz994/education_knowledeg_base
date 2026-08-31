from typing import Any

from pydantic import BaseModel, Field


class QueryRequestSchema(BaseModel):
    query: str
    session_id: str
    is_stream: bool


class QueryStreamResponseSchema(BaseModel):
    message: str
    session_id: str


class QueryResponseSchema(BaseModel):
    message: str
    session_id: str
    answer: str
    done_list: list
    image_urls: list


class ClearHistoryResponseSchema(BaseModel):
    message: str
    deleted_count: int


class HistoryItemSchema(BaseModel):
    id: str = ''
    session_id: str = ''
    role: str = ''
    text: str = ''
    rewritten_query: str = ''
    item_names: list[str] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    ts: Any = None

class HistoryResponseSchema(BaseModel):
    session_id: str
    items:list[HistoryItemSchema] = Field(default_factory=list)