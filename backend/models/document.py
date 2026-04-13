from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class DocumentUpload(BaseModel):
    filename: str
    content_type: str
    size: int


class TextChunk(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    text: str
    index: int
    metadata: dict = Field(default_factory=dict)


class DocumentMeta(BaseModel):
    id: str
    filename: str
    ext: str
    size: int
    pages: Optional[int] = None
    status: DocumentStatus = DocumentStatus.PENDING
    chunks: list[TextChunk] = Field(default_factory=list)
    extracted_text: str = ""
