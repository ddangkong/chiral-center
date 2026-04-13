from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class ReportFormat(str, Enum):
    MARKDOWN = "markdown"
    PDF = "pdf"
    JSON = "json"


class ReportSection(BaseModel):
    title: str
    content: str
    order: int = 0
    subsections: list['ReportSection'] = Field(default_factory=list)


class Report(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    simulation_id: str
    title: str = ""
    summary: str = ""
    sections: list[ReportSection] = Field(default_factory=list)
    format: ReportFormat = ReportFormat.MARKDOWN
    raw_markdown: str = ""
    metadata: dict = Field(default_factory=dict)
