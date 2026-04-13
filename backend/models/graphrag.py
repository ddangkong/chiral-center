"""GraphRAG data models."""
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class GraphRAGStatus(str, Enum):
    IDLE = "idle"
    INDEXING = "indexing"
    READY = "ready"
    ERROR = "error"


class Community(BaseModel):
    id: int
    title: str = ""
    summary: str = ""
    entities: list[str] = Field(default_factory=list)
    level: int = 0
    weight: float = 0.0


class GraphRAGEntity(BaseModel):
    name: str
    type: str = ""
    description: str = ""
    community_id: int = -1


class GraphRAGRelation(BaseModel):
    source: str
    target: str
    description: str = ""
    weight: float = 1.0


class GraphRAGIndex(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    ontology_id: str = ""
    status: GraphRAGStatus = GraphRAGStatus.IDLE
    entities: list[GraphRAGEntity] = Field(default_factory=list)
    relations: list[GraphRAGRelation] = Field(default_factory=list)
    communities: list[Community] = Field(default_factory=list)
    text_chunks: list[str] = Field(default_factory=list)
    error: str = ""


class GraphRAGQueryResult(BaseModel):
    answer: str
    context_entities: list[str] = Field(default_factory=list)
    context_communities: list[str] = Field(default_factory=list)
    search_type: str = "local"
