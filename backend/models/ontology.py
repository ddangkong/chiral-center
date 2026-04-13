from pydantic import BaseModel, Field
from typing import Optional


class EntityType(BaseModel):
    name: str
    description: str = ""
    attributes: list[str] = Field(default_factory=list)


class RelationType(BaseModel):
    name: str
    description: str = ""
    source_type: str = ""
    target_type: str = ""


class Entity(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    name: str
    type: str
    attributes: dict = Field(default_factory=dict)
    description: str = ""


class Relation(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    source_id: str
    target_id: str
    relation_type: str
    weight: float = 1.0
    description: str = ""


class OntologySchema(BaseModel):
    entity_types: list[EntityType] = Field(default_factory=list)
    relation_types: list[RelationType] = Field(default_factory=list)


class OntologyResult(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    schema_def: OntologySchema
    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    topic: str = ""
    purpose: str = ""
