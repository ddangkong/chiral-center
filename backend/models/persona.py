from pydantic import BaseModel, Field
from typing import Optional


class BigFiveTraits(BaseModel):
    """Big Five personality traits (0.0 ~ 1.0)."""
    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5


class CommunicationStyle(BaseModel):
    """How this persona communicates in discussions."""
    formality: str = "neutral"        # formal / neutral / casual
    verbosity: str = "moderate"       # terse / moderate / verbose
    argument_style: str = "balanced"  # data-driven / anecdotal / authoritative / balanced
    tone: str = "professional"        # aggressive / assertive / professional / diplomatic / passive


class PersonaProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    name: str
    role: str = ""
    description: str = ""
    personality: str = ""
    stance: str = ""  # 입장/관점
    goals: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    relationships: dict[str, str] = Field(default_factory=dict)  # persona_id -> relationship description
    # Deep persona spec (TinyTroupe-inspired)
    big_five: BigFiveTraits = Field(default_factory=BigFiveTraits)
    communication_style: CommunicationStyle = Field(default_factory=CommunicationStyle)
    beliefs: list[str] = Field(default_factory=list)
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    background: str = ""  # detailed professional background
    entity_knowledge: list[str] = Field(default_factory=list)  # grounded facts from ontology
    # Fixed-role agent fields (discussion mode only)
    agent_tier: str = "dynamic"  # "core" | "support" | "dynamic"(legacy)
    fixed_role_id: Optional[str] = None  # e.g. "market_analyst", "devils_advocate"
    strategic_framework: str = ""  # W5H + How to Win prompt section
    must_speak: bool = False  # True = skip 불가 (악마의 변호인 등)
    can_request_data: bool = False  # True = data_request 가능


class PersonaAction(BaseModel):
    persona_id: str
    action_type: str  # post, reply, repost, follow
    content: str = ""
    target_id: Optional[str] = None
    round_num: int = 0
