from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class SimStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


class SimPlatform(str, Enum):
    TWITTER = "twitter"
    REDDIT = "reddit"
    DISCUSSION = "discussion"


class SimConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    ontology_id: str
    platform: SimPlatform = SimPlatform.DISCUSSION
    num_rounds: int = 10
    personas: list[str] = Field(default_factory=list)  # persona IDs
    topic: str = ""
    injection_events: list[dict] = Field(default_factory=list)  # God's-eye interventions


class SimEvent(BaseModel):
    round_num: int
    timestamp: str = ""
    persona_id: str
    persona_name: str = ""
    action_type: str  # post, reply, repost, skip, question, concede, propose, cite
    content: str = ""
    target_id: Optional[str] = None
    thread_id: Optional[str] = None       # 스레드 루트 이벤트 ID
    parent_event_id: Optional[str] = None  # 직접 부모 이벤트 ID
    event_id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    data_request: Optional[str] = None  # 에이전트가 요청한 데이터 (지원 에이전트 호출 트리거)
    metadata: dict = Field(default_factory=dict)


class SimResult(BaseModel):
    id: str
    config: SimConfig
    status: SimStatus = SimStatus.IDLE
    events: list[SimEvent] = Field(default_factory=list)
    current_round: int = 0
    total_rounds: int = 0
