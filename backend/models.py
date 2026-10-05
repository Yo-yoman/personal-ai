"""Pydantic request/response models."""
from typing import Literal

from pydantic import BaseModel, Field


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[HistoryMessage] = Field(default_factory=list)
    debug: bool = False


class DocumentInfo(BaseModel):
    filename: str
    chunks: int
    pages: int
    size_kb: float


class UploadResponse(BaseModel):
    filename: str
    chunks: int
    message: str
