"""TinyTroupe 패턴: 2단계 메모리 (Episodic + Semantic + Reflection)."""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from llm.base import BaseLLMClient

logger = logging.getLogger(__name__)


@dataclass
class DiscussionEvent:
    """에피소드 메모리의 단일 이벤트."""
    event_id: str
    round_num: int
    speaker_id: str
    speaker_name: str
    speaker_role: str
    action_type: str  # post, reply, question, concede, propose, cite, skip
    content: str
    target_id: Optional[str] = None
    thread_id: Optional[str] = None
    parent_event_id: Optional[str] = None


@dataclass
class SemanticMemory:
    """시맨틱 메모리: LLM reflection으로 압축된 지식."""
    key_positions: dict[str, str] = field(default_factory=dict)  # agent_name -> 현재 입장
    data_points: list[str] = field(default_factory=list)          # 인용된 구체적 수치/사실
    agreements: list[str] = field(default_factory=list)           # 합의된 사항
    concessions: list[str] = field(default_factory=list)          # 양보/입장 변경
    open_questions: list[str] = field(default_factory=list)       # 미답변 질문
    key_disputes: list[str] = field(default_factory=list)         # 핵심 쟁점


class DiscussionMemoryManager:
    """에이전트별 에피소드+시맨틱 메모리 관리. 주기적 reflection."""

    def __init__(self, llm: BaseLLMClient, reflection_interval: int = 3):
        self.llm = llm
        self.reflection_interval = reflection_interval
        # agent_id -> list of DiscussionEvent
        self.episodic: dict[str, list[DiscussionEvent]] = {}
        # 전체 공유 시맨틱 메모리
        self.semantic = SemanticMemory()
        # 전체 이벤트 (에이전트 무관)
        self.all_events: list[DiscussionEvent] = []
        self._last_reflection_round = 0

    def record_event(self, event: DiscussionEvent):
        """이벤트를 에피소드 메모리에 기록."""
        self.all_events.append(event)
        if event.speaker_id not in self.episodic:
            self.episodic[event.speaker_id] = []
        self.episodic[event.speaker_id].append(event)

    def get_agent_memory(self, agent_id: str, max_recent: int = 10) -> str:
        """에이전트의 메모리를 프롬프트용 텍스트로 반환."""
        parts = []

        # 시맨틱 메모리 (전체 공유)
        sem = self._format_semantic()
        if sem:
            parts.append(f"[토론 상태 요약]\n{sem}")

        # 에이전트 고유 에피소드 (최근 N개)
        agent_events = self.episodic.get(agent_id, [])
        if agent_events:
            recent = agent_events[-max_recent:]
            own_history = "\n".join(
                f"  라운드{e.round_num}: [{e.action_type}] {e.content[:200]}"
                for e in recent
            )
            parts.append(f"[나의 이전 발언]\n{own_history}")

        return "\n\n".join(parts)

    def get_recent_discussion(self, max_events: int = 20) -> str:
        """최근 전체 토론 내용 (모든 에이전트)."""
        recent = self.all_events[-max_events:]
        if not recent:
            return ""
        lines = []
        for e in recent:
            prefix = f"[라운드{e.round_num}] {e.speaker_name}({e.speaker_role})"
            action_label = {
                "post": "발언", "reply": "응답", "question": "질문",
                "concede": "양보", "propose": "제안", "cite": "인용", "skip": "패스"
            }.get(e.action_type, e.action_type)
            lines.append(f"{prefix} [{action_label}]: {e.content}")
        return "\n".join(lines)

    async def maybe_reflect(self, current_round: int):
        """N라운드마다 reflection 실행 → 시맨틱 메모리 업데이트."""
        if current_round - self._last_reflection_round < self.reflection_interval:
            return
        if not self.all_events:
            return

        self._last_reflection_round = current_round
        await self._run_reflection()

    async def _run_reflection(self):
        """LLM으로 에피소드 메모리를 시맨틱 메모리로 압축."""
        # 최근 이벤트만 reflection 대상
        recent_text = self.get_recent_discussion(30)
        if not recent_text:
            return

        prompt = f"""다음은 회의 토론의 최근 내용입니다. 이 내용을 분석하여 토론 상태를 정리하세요.

{recent_text}

다음 JSON 형식으로 응답하세요:
{{
  "key_positions": {{"에이전트명": "현재 핵심 입장 (1-2문장)"}},
  "data_points": ["인용된 구체적 수치/사실1", "수치2"],
  "agreements": ["합의된 사항1", "합의2"],
  "concessions": ["입장을 변경하거나 양보한 내용"],
  "open_questions": ["아직 답변되지 않은 질문"],
  "key_disputes": ["핵심 쟁점/갈등 포인트"]
}}"""

        try:
            response = await self.llm.complete(
                [
                    {"role": "system", "content": "당신은 회의 기록 분석가입니다. 토론 내용을 구조화된 요약으로 정리합니다. JSON만 응답하세요."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=1500,
            )
            data = self._parse_json(response)
            self.semantic.key_positions = data.get("key_positions", self.semantic.key_positions)
            self.semantic.data_points = data.get("data_points", self.semantic.data_points)
            self.semantic.agreements = data.get("agreements", self.semantic.agreements)
            self.semantic.concessions = data.get("concessions", self.semantic.concessions)
            self.semantic.open_questions = data.get("open_questions", self.semantic.open_questions)
            self.semantic.key_disputes = data.get("key_disputes", self.semantic.key_disputes)
            logger.info(f"reflection_complete round={self._last_reflection_round} positions={len(self.semantic.key_positions)} agreements={len(self.semantic.agreements)}")
        except Exception as e:
            logger.error(f"Reflection error: {e}")

    def _format_semantic(self) -> str:
        """시맨틱 메모리를 프롬프트용 텍스트로 포맷."""
        s = self.semantic
        parts = []
        if s.agreements:
            parts.append("합의 사항: " + "; ".join(s.agreements))
        if s.key_disputes:
            parts.append("핵심 쟁점: " + "; ".join(s.key_disputes))
        if s.data_points:
            parts.append("인용된 데이터: " + "; ".join(s.data_points[:10]))
        if s.open_questions:
            parts.append("미답변 질문: " + "; ".join(s.open_questions))
        if s.concessions:
            parts.append("입장 변경: " + "; ".join(s.concessions))
        if s.key_positions:
            pos = "; ".join(f"{k}: {v}" for k, v in s.key_positions.items())
            parts.append("각 참여자 입장: " + pos)
        return "\n".join(parts)

    def _parse_json(self, text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)
