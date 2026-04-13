"""러닝 디스커션 브리프 + 스레드 트리 관리."""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from llm.base import BaseLLMClient
from core.discussion_memory import DiscussionEvent

logger = logging.getLogger(__name__)


@dataclass
class DiscussionBrief:
    """매 라운드 후 생성되는 토론 상태 요약."""
    round_num: int = 0
    agreed_facts: list[str] = field(default_factory=list)
    open_disputes: list[str] = field(default_factory=list)
    cited_data: list[str] = field(default_factory=list)
    raised_questions: list[str] = field(default_factory=list)
    moderator_feedback: str = ""
    next_focus: str = ""


class ThreadTree:
    """대화 스레드 트리. reply 체인을 추적."""

    def __init__(self):
        self.events: dict[str, DiscussionEvent] = {}  # event_id -> event
        self.children: dict[str, list[str]] = {}       # event_id -> [child_event_ids]
        self.roots: list[str] = []                      # 루트 이벤트 IDs

    def add_event(self, event: DiscussionEvent):
        """이벤트 추가. 부모가 있으면 자식으로 연결."""
        self.events[event.event_id] = event
        if event.parent_event_id and event.parent_event_id in self.events:
            if event.parent_event_id not in self.children:
                self.children[event.parent_event_id] = []
            self.children[event.parent_event_id].append(event.event_id)
        else:
            self.roots.append(event.event_id)

    def get_thread_context(self, event_id: str, max_depth: int = 5) -> list[DiscussionEvent]:
        """이벤트의 스레드 맥락 (부모→조부모 체인)."""
        chain = []
        current_id = event_id
        for _ in range(max_depth):
            event = self.events.get(current_id)
            if not event:
                break
            chain.append(event)
            if not event.parent_event_id:
                break
            current_id = event.parent_event_id
        chain.reverse()
        return chain

    def format_thread(self, event_id: str) -> str:
        """스레드를 프롬프트용 텍스트로 포맷."""
        chain = self.get_thread_context(event_id)
        if not chain:
            return ""
        lines = []
        for i, e in enumerate(chain):
            indent = "  " * i
            lines.append(f"{indent}{'└ ' if i > 0 else ''}{e.speaker_name}({e.speaker_role}) [{e.action_type}]: {e.content[:300]}")
        return "\n".join(lines)

    def get_active_threads(self, max_threads: int = 5) -> list[str]:
        """최근 활성 스레드 루트 IDs."""
        # 가장 최근에 자식이 추가된 스레드 우선
        thread_activity: dict[str, int] = {}
        for eid, event in self.events.items():
            tid = event.thread_id or eid
            round_num = event.round_num
            if tid not in thread_activity or round_num > thread_activity[tid]:
                thread_activity[tid] = round_num
        sorted_threads = sorted(thread_activity.items(), key=lambda x: x[1], reverse=True)
        return [tid for tid, _ in sorted_threads[:max_threads]]


class DiscussionStateTracker:
    """매 라운드 토론 상태를 추적하고 브리프를 생성."""

    def __init__(self, llm: BaseLLMClient):
        self.llm = llm
        self.thread_tree = ThreadTree()
        self.briefs: list[DiscussionBrief] = []
        self.current_brief: Optional[DiscussionBrief] = None

    def record_event(self, event: DiscussionEvent):
        """이벤트를 스레드 트리에 추가."""
        self.thread_tree.add_event(event)

    async def generate_brief(self, round_num: int, recent_events: list[DiscussionEvent]) -> DiscussionBrief:
        """라운드 후 토론 브리프 생성."""
        if not recent_events:
            return DiscussionBrief(round_num=round_num)

        events_text = "\n".join(
            f"[{e.speaker_name}({e.speaker_role})] [{e.action_type}]: {e.content}"
            for e in recent_events
        )

        # 이전 브리프가 있으면 포함
        prev_context = ""
        if self.current_brief:
            prev_parts = []
            if self.current_brief.agreed_facts:
                prev_parts.append("이전 합의: " + "; ".join(self.current_brief.agreed_facts))
            if self.current_brief.open_disputes:
                prev_parts.append("이전 쟁점: " + "; ".join(self.current_brief.open_disputes))
            prev_context = "\n".join(prev_parts)

        prompt = f"""라운드 {round_num}의 토론 내용을 분석하여 토론 상태를 업데이트하세요.

{f"이전 토론 상태:{chr(10)}{prev_context}{chr(10)}" if prev_context else ""}
이번 라운드 발언:
{events_text}

JSON 형식:
{{
  "agreed_facts": ["이번 라운드에서 합의된/확인된 사실"],
  "open_disputes": ["아직 해결 안 된 핵심 쟁점"],
  "cited_data": ["인용된 구체적 수치/데이터"],
  "raised_questions": ["제기된 질문 중 미답변"],
  "next_focus": "다음 라운드에서 집중해야 할 논점 (1문장)"
}}"""

        try:
            response = await self.llm.complete(
                [
                    {"role": "system", "content": "회의 진행 상태를 추적합니다. JSON만 응답."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=1000,
            )
            data = self._parse_json(response)
            brief = DiscussionBrief(
                round_num=round_num,
                agreed_facts=data.get("agreed_facts", []),
                open_disputes=data.get("open_disputes", []),
                cited_data=data.get("cited_data", []),
                raised_questions=data.get("raised_questions", []),
                next_focus=data.get("next_focus", ""),
            )
            self.current_brief = brief
            self.briefs.append(brief)
            return brief
        except Exception as e:
            logger.error(f"Brief generation error: {e}")
            return DiscussionBrief(round_num=round_num)

    def format_brief_for_prompt(self) -> str:
        """현재 브리프를 에이전트 프롬프트에 주입할 텍스트로 변환."""
        b = self.current_brief
        if not b:
            return ""
        parts = [f"[토론 진행 상태 — 라운드 {b.round_num} 기준]"]
        if b.agreed_facts:
            parts.append("✅ 합의 사항: " + "; ".join(b.agreed_facts))
        if b.open_disputes:
            parts.append("⚡ 미해결 쟁점: " + "; ".join(b.open_disputes))
        if b.cited_data:
            parts.append("📊 인용된 데이터: " + "; ".join(b.cited_data))
        if b.raised_questions:
            parts.append("❓ 미답변 질문: " + "; ".join(b.raised_questions))
        if b.next_focus:
            parts.append("🎯 다음 집중 논점: " + b.next_focus)
        if b.moderator_feedback:
            parts.append("📋 진행자 코멘트: " + b.moderator_feedback)
        return "\n".join(parts)

    def _parse_json(self, text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)
