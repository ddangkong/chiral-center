"""Per-agent conversation context manager (TinyTroupe-inspired).

Maintains multi-turn message history for each agent so the LLM can
remember previous statements, maintain stance consistency, and build
on prior arguments across simulation rounds.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from llm.base import BaseLLMClient
from models.persona import PersonaProfile
from utils.logger import log


def _append_directives(prompt: str, global_directive: str = "", role_override: str = "") -> str:
    """Append optional directives to an existing system prompt."""
    sections = [prompt]
    if global_directive:
        sections.append(f"[Additional Directive]\n{global_directive}")
    if role_override:
        sections.append(f"[Role-specific Directive]\n{role_override}")
    return "\n\n".join(section for section in sections if section)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AgentContext:
    """Holds one agent's accumulated conversation state."""
    persona_id: str
    history_pairs: list[dict] = field(default_factory=list)
    # Each pair: {"user": str, "assistant": str, "round": int}
    memory_summary: str = ""
    turns_count: int = 0


# ---------------------------------------------------------------------------
# System-prompt builder helpers
# ---------------------------------------------------------------------------

def _big_five_to_text(bf) -> str:
    """Translate Big Five scores to natural-language behavioral tendencies."""
    lines = []

    if bf.openness > 0.7:
        lines.append("새로운 아이디어와 비전통적 접근에 열린 편입니다")
    elif bf.openness < 0.3:
        lines.append("검증된 방법과 실용적 접근을 선호합니다")

    if bf.conscientiousness > 0.7:
        lines.append("체계적이고 계획적으로 일합니다")
    elif bf.conscientiousness < 0.3:
        lines.append("유연하고 즉흥적인 판단을 내릴 때가 많습니다")

    if bf.extraversion > 0.7:
        lines.append("적극적으로 의견을 개진하고 토론을 주도합니다")
    elif bf.extraversion < 0.3:
        lines.append("신중하게 경청한 뒤 핵심만 짧게 발언합니다")

    if bf.agreeableness > 0.7:
        lines.append("협력과 타협을 중시합니다")
    elif bf.agreeableness < 0.3:
        lines.append("자기 부서 입장을 강하게 고수하며 쉽게 양보하지 않습니다")

    if bf.neuroticism > 0.7:
        lines.append("리스크와 부정적 시나리오에 민감하게 반응합니다")
    elif bf.neuroticism < 0.3:
        lines.append("압박 상황에서도 침착하게 판단합니다")

    return "; ".join(lines) if lines else "균형 잡힌 성격"


def _comm_style_to_text(cs) -> str:
    """Translate CommunicationStyle to a short instruction."""
    parts = []
    style_map = {
        "formal": "격식체로 발언하세요",
        "casual": "편한 구어체로 발언하세요",
        "terse": "짧고 핵심만 발언하세요",
        "verbose": "상세하고 분석적으로 발언하세요",
        "data-driven": "수치와 데이터 근거 중심으로 논증하세요",
        "anecdotal": "구체적 사례와 경험 중심으로 논증하세요",
        "authoritative": "전문가로서 단정적으로 논증하세요",
        "aggressive": "공격적이고 도발적인 톤으로 발언하세요",
        "assertive": "자신감 있고 단호한 톤으로 발언하세요",
        "diplomatic": "외교적이고 중립적인 톤으로 발언하세요",
        "passive": "조심스럽고 수동적인 톤으로 발언하세요",
    }
    for val in [cs.formality, cs.verbosity, cs.argument_style, cs.tone]:
        if val in style_map:
            parts.append(style_map[val])
    return "; ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Prompt templates for current turn
# ---------------------------------------------------------------------------

TURN_PROMPT_TWITTER = """안건: {topic}

최근 발언:
{recent_posts}

현재 {round_num}/{total_rounds} 라운드입니다.

발언 규칙:
- 화면이 Twitter 형식처럼 보이더라도 실제 280자 제한은 적용하지 마세요
- 반드시 최소 1500자 이상, 권장 1500-2200자로 작성하세요
- 논점을 3개 이상 단락으로 나누고, 수치와 사례와 반론 대응을 포함하세요

행동 선택 (하나만) — 모든 행동은 최소 1500자, 권장 1500-2200자:
1. "post" - 발언 (최소 1500자, 권장 1500-2200자)
2. "reply" - 다른 발언에 답변 (최소 1500자, target_post 포함, 상대 논점을 구체적으로 인용하며 반박/지지)
3. "repost" - 공유 + 심층 코멘트 (최소 1500자, 원문에 대한 분석적 해설)
4. "skip" - 이번 라운드 패스

JSON으로 응답:
{{
  "action": "post|reply|repost|skip",
  "content": "한국어 발언 (최소 1500자, 권장 1500-2200자, 부서 관점, 구체적 근거와 수치 포함)",
  "target_post": null 또는 발언번호,
  "reasoning": "내부 판단 근거"
}}
"""

TURN_PROMPT_REDDIT = """안건: {topic}

최근 발언:
{recent_posts}

현재 {round_num}/{total_rounds} 라운드입니다.

발언 규칙:
- Reddit 형식처럼 보이더라도 짧은 댓글이 아니라 내부 전략 메모 수준으로 작성하세요
- 반드시 최소 1500자 이상, 권장 1500-2200자로 작성하세요
- 논점을 3개 이상 단락으로 나누고, 수치와 사례와 반론 대응을 포함하세요

행동 선택 (하나만) — 모든 행동은 최소 1500자, 권장 1500-2200자:
1. "post" - 상세 발언 (최소 1500자, 권장 1500-2200자)
2. "reply" - 답변 (최소 1500자, target_post 포함, 상대 논점을 구체적으로 인용하며 반박/지지)
3. "repost" - 공유 + 심층 코멘트 (최소 1500자, 원문에 대한 분석적 해설)
4. "skip" - 패스

JSON으로 응답:
{{
  "action": "post|reply|repost|skip",
  "content": "한국어 발언 (최소 1500자, 권장 1500-2200자, 부서 관점, 분석적, 근거와 수치 포함)",
  "target_post": null 또는 발언번호,
  "reasoning": "내부 판단 근거"
}}
"""

TURN_PROMPT_DISCUSSION = """안건: {topic}

{discussion_brief}

{memory_context}

최근 토론 (최근 30건):
{recent_posts}

{moderator_feedback}

현재 {round_num}/{total_rounds} 라운드입니다.

=== 행동 선택 (하나만) — 모든 행동은 최소 1500자, 권장 1500-2200자 ===
1. "post" - 새 논점 제시 (최소 1500자, 권장 1500-2200자, 구체적 근거와 수치 필수)
2. "reply" - 특정 발언에 응답 (최소 1500자, target_post 필수, 상대 논점을 구체적으로 인용하며 반박/지지 + 자기 부서 근거 제시)
3. "question" - 데이터/근거 요청 + 배경 분석 (최소 1500자, target_post 필수, 왜 이 데이터가 필요한지 맥락과 가설 포함)
4. "concede" - 부분 동의 + 입장 수정 (최소 1500자, target_post 필수, 인정하는 부분과 여전히 고수하는 부분을 구체적 근거로 구분)
5. "propose" - 타협안/구체적 행동 제안 (최소 1500자, 실행 단계, 비용, 일정까지 포함)
6. "cite" - 이전 토론 포인트 인용 + 심화 분석 (최소 1500자, target_post 필수, 인용한 논점을 확장/발전)
7. "skip" - 이번 라운드에 추가 발언 없음

=== 발언 규칙 ===
- **절대 규칙: 반드시 1500자 이상 작성하세요. 1500자 미만은 재작성 대상입니다.**
- 논점을 3개 이상의 단락으로 구조화하세요
- 구체적 수치, 기업명, 사례를 반드시 포함
- 이전 라운드에서 제기된 쟁점이나 질문에 우선 대응
- 합의된 사항을 반복하지 말고, 미해결 쟁점에 집중
- 감정적 표현보다 데이터 기반 논증
- 수치나 내부 데이터가 필요하면 data_request에 구체적으로 기술
- 다른 분석관의 발언을 직접 인용하며 응답하세요

JSON으로 응답:
{{
  "action": "post|reply|question|concede|propose|cite|skip",
  "content": "한국어 발언 (최소 1500자, 권장 1500-2200자, 역할 관점, 구체적 근거와 수치 포함)",
  "data_request": "필요한 데이터를 구체적으로 기술 (없으면 null)",
  "target_post": null 또는 발언번호,
  "reasoning": "내부 판단 근거 (W5H 중 어떤 차원에 대응하는지 명시)"
}}
"""

MEMORY_CONSOLIDATION_PROMPT = """다음은 "{persona_name}" ({role})이 조직 전략 회의에서 이전 라운드에 한 발언과 맥락입니다.

{turns_text}

이 사람의 참여 이력을 2~3문장으로 요약하세요.
포함할 내용:
- 주요 입장과 핵심 주장
- 제시한 근거나 수치
- 다른 부서 발언에 대한 반응
- 입장 변화가 있었다면 그 방향

한국어로 간결하게 작성하세요."""


# ---------------------------------------------------------------------------
# ConversationManager
# ---------------------------------------------------------------------------

class ConversationManager:
    """Manages per-agent multi-turn conversation context."""

    def __init__(
        self,
        llm: BaseLLMClient,
        max_history_turns: int = 6,
        max_input_tokens: int = 3000,
        full_context_mode: bool = False,
    ):
        self.llm = llm
        self.max_history_turns = max_history_turns
        self.max_input_tokens = max_input_tokens
        self.full_context_mode = full_context_mode
        self._contexts: dict[str, AgentContext] = {}
        # Discussion mode injection slots
        self._discussion_brief: str = ""
        self._moderator_feedback: str = ""
        self._memory_context: str = ""

    def inject_discussion_brief(self, brief_text: str):
        """토론 브리프를 다음 턴 프롬프트에 주입."""
        self._discussion_brief = brief_text

    def inject_moderator_feedback(self, feedback: str):
        """모더레이터 피드백을 다음 턴 프롬프트에 주입."""
        self._moderator_feedback = f"[진행자 코멘트] {feedback}" if feedback else ""

    def inject_memory_context(self, memory_text: str):
        """에이전트별 메모리를 다음 턴 프롬프트에 주입."""
        self._memory_context = memory_text

    # -- context access -----------------------------------------------------

    def get_or_create(self, persona_id: str) -> AgentContext:
        if persona_id not in self._contexts:
            self._contexts[persona_id] = AgentContext(persona_id=persona_id)
        return self._contexts[persona_id]

    # -- build messages -----------------------------------------------------

    def build_messages(
        self,
        persona: PersonaProfile,
        topic: str,
        post_history: list[dict],
        round_num: int,
        total_rounds: int,
        platform: str = "discussion",
        ontology_context: str = "",
        global_directive: str = "",
        role_override: str = "",
    ) -> list[dict]:
        """Assemble the full multi-turn message list for one agent's turn."""

        system_prompt = self._build_system_prompt(
            persona, round_num, total_rounds,
            ontology_context, global_directive, role_override,
        )
        current_turn = self._build_current_turn(
            topic, post_history, round_num, total_rounds, platform,
        )

        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        ctx = self.get_or_create(persona.id)

        # Inject memory summary
        if ctx.memory_summary:
            messages.append({
                "role": "user",
                "content": f"[이전 논의 요약]\n{ctx.memory_summary}",
            })
            messages.append({
                "role": "assistant",
                "content": "네, 이전 논의 내용을 숙지했습니다. 이어서 부서 입장에서 참여하겠습니다.",
            })

        # Append recent history pairs (multi-turn)
        if self.full_context_mode:
            recent_pairs = ctx.history_pairs  # 풀 컨텍스트: 전체 히스토리 유지
        else:
            recent_pairs = ctx.history_pairs[-self.max_history_turns:]
        for pair in recent_pairs:
            messages.append({"role": "user", "content": pair["user"]})
            messages.append({"role": "assistant", "content": pair["assistant"]})

        # Current turn prompt
        messages.append({"role": "user", "content": current_turn})

        # Enforce token budget — drop oldest history if needed (풀 컨텍스트 모드에서는 비활성화)
        if not self.full_context_mode:
            messages = self._enforce_token_budget(messages)

        return messages

    # -- record & consolidate -----------------------------------------------

    def record_response(
        self, persona_id: str, user_prompt: str, assistant_response: str, round_num: int = 0,
    ):
        """Record a completed turn for an agent."""
        ctx = self.get_or_create(persona_id)
        ctx.history_pairs.append({
            "user": user_prompt,
            "assistant": assistant_response,
            "round": round_num,
        })
        ctx.turns_count += 1

    async def consolidate_memory(self, persona: PersonaProfile):
        """Compress oldest history pairs into a summary to save tokens."""
        ctx = self.get_or_create(persona.id)

        if ctx.turns_count <= self.max_history_turns:
            return

        # Pairs to consolidate (everything except the most recent window)
        keep_count = self.max_history_turns
        to_consolidate = ctx.history_pairs[:-keep_count]

        if not to_consolidate:
            return

        # Build text from turns to consolidate
        turns_lines = []
        for pair in to_consolidate:
            # Extract just the assistant response (the agent's actual statement)
            try:
                data = json.loads(pair["assistant"])
                content = data.get("content", pair["assistant"][:200])
                action = data.get("action", "post")
            except (json.JSONDecodeError, TypeError):
                content = pair["assistant"][:200]
                action = "post"

            round_label = f"라운드 {pair.get('round', '?')}"
            turns_lines.append(f"[{round_label}] ({action}) {content}")

        turns_text = "\n".join(turns_lines)

        # Prepend existing summary if any
        if ctx.memory_summary:
            turns_text = f"[기존 요약] {ctx.memory_summary}\n\n[새로운 발언]\n{turns_text}"

        prompt = MEMORY_CONSOLIDATION_PROMPT.format(
            persona_name=persona.name,
            role=persona.role,
            turns_text=turns_text,
        )

        try:
            summary = await self.llm.complete(
                [
                    {"role": "system", "content": "회의 참여 이력을 간결하게 요약하는 역할입니다. 한국어로 2~3문장만 작성하세요."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=300,
            )
            ctx.memory_summary = summary.strip()[:500]
            log.info("memory_consolidated", persona=persona.name, summary_len=len(ctx.memory_summary))
        except Exception as e:
            log.warning("memory_consolidation_failed", persona=persona.name, error=str(e))

        # Drop consolidated pairs, keep recent window
        ctx.history_pairs = ctx.history_pairs[-keep_count:]

    # -- internal helpers ---------------------------------------------------

    def _build_system_prompt(
        self,
        persona: PersonaProfile,
        round_num: int,
        total_rounds: int,
        ontology_context: str = "",
        global_directive: str = "",
        role_override: str = "",
    ) -> str:
        """Build a rich system prompt from the full persona spec."""

        # 고정 역할 에이전트: strategic_framework 사용
        if persona.fixed_role_id and persona.agent_tier in ("core", "support"):
            prompt = _append_directives(
                persona.strategic_framework,
                global_directive=global_directive,
                role_override=role_override,
            )
            if False:
                prompt += f"\n\n[추가 지시] {global_directive}"
            prompt += f"\n\n현재 {round_num}/{total_rounds} 라운드입니다."
            return prompt

        # Legacy: 동적 페르소나 (twitter/reddit/이전 discussion)
        sections = []

        # Identity
        sections.append(f"당신은 {persona.name}, {persona.role}입니다.")

        # Background
        if persona.background:
            sections.append(f"[경력 배경] {persona.background}")

        # Personality (Big Five)
        bf_text = _big_five_to_text(persona.big_five)
        if bf_text:
            sections.append(f"[성격 특성] {bf_text}")
        if persona.personality:
            sections.append(f"[성격 요약] {persona.personality}")

        # Communication style
        cs_text = _comm_style_to_text(persona.communication_style)
        if cs_text:
            sections.append(f"[소통 방식] {cs_text}")

        # Beliefs
        if persona.beliefs:
            sections.append(f"[핵심 가치] {'; '.join(persona.beliefs)}")

        # Likes / Dislikes
        if persona.likes:
            sections.append(f"[선호] {', '.join(persona.likes)}")
        if persona.dislikes:
            sections.append(f"[비선호] {', '.join(persona.dislikes)}")

        # Department info
        sections.append(f"[우리 부서 입장] {persona.stance}")
        if persona.goals:
            sections.append(f"[부서 목표] {', '.join(persona.goals)}")
        if persona.knowledge:
            sections.append(f"[전문 분야] {', '.join(persona.knowledge)}")

        # Entity-grounded knowledge
        if persona.entity_knowledge:
            sections.append("[배경 지식 - 지식 그래프 기반]")
            for fact in persona.entity_knowledge:
                sections.append(f"  - {fact}")

        # Ontology context
        if ontology_context:
            sections.append(f"[참고 자료]\n{ontology_context}")

        # Relationships
        if persona.relationships:
            rel_lines = [f"  - {desc}" for desc in persona.relationships.values()]
            sections.append("[관계]\n" + "\n".join(rel_lines))

        # Rules
        sections.append(
            "[행동 규칙]\n"
            "- **절대 규칙: 모든 발언(post, reply, repost 포함)은 반드시 최소 1500자 이상 작성하세요. 1500자 미만은 불합격입니다.**\n"
            "- 반드시 당신 부서의 이해관계와 전문성에서 발언하세요\n"
            "- 이전 라운드에서 한 발언과 일관성을 유지하세요\n"
            "- 다른 발언에 반응할 때 구체적으로 인용하며 동의/반박하세요\n"
            "- 논점을 3개 이상 단락으로 구조화하고, 구체적 수치/사례/근거를 반드시 포함하세요\n"
            "- reply도 짧은 댓글이 아니라 심층 분석 보고서 수준으로 작성하세요\n"
            "- 절대 금지: '시뮬레이션', 'AI', '연습', '역할극' 등 메타 발언\n"
            f"- 현재 {round_num}/{total_rounds} 라운드입니다"
        )

        # Extra directives
        if global_directive:
            sections.append(f"[추가 지시] {global_directive}")
        if role_override:
            sections.append(f"[부서 특별 지시] {role_override}")

        sections.append("JSON으로만 응답. content는 반드시 한국어.")

        return "\n\n".join(sections)

    def _build_current_turn(
        self,
        topic: str,
        post_history: list[dict],
        round_num: int,
        total_rounds: int,
        platform: str,
    ) -> str:
        """Build the current turn's user prompt with recent posts."""
        max_recent = 30 if platform == "discussion" else 15
        recent = post_history[-max_recent:] if post_history else []
        if recent:
            recent_text = "\n".join(
                f"[#{p['post_num']}] @{p['author']}: {p['content']}"
                for p in recent
            )
        else:
            recent_text = "(아직 발언이 없습니다 - 첫 발언자 중 한 명입니다)"

        if platform == "discussion":
            return TURN_PROMPT_DISCUSSION.format(
                topic=topic,
                discussion_brief=self._discussion_brief or "",
                memory_context=self._memory_context or "",
                recent_posts=recent_text,
                moderator_feedback=self._moderator_feedback or "",
                round_num=round_num,
                total_rounds=total_rounds,
            )

        template = TURN_PROMPT_REDDIT if platform == "reddit" else TURN_PROMPT_TWITTER
        return template.format(
            topic=topic,
            recent_posts=recent_text,
            round_num=round_num,
            total_rounds=total_rounds,
        )

    def _enforce_token_budget(self, messages: list[dict]) -> list[dict]:
        """Drop oldest history pairs if total tokens exceed budget."""
        total = self._estimate_tokens(messages)

        if total <= self.max_input_tokens:
            return messages

        # Find history pair boundaries (skip system[0], memory summary[1:2], current turn[-1])
        # Drop pairs from the front of history until under budget
        while total > self.max_input_tokens and len(messages) > 3:
            # Find the first user/assistant pair after system message (and optional memory)
            # Don't remove: messages[0] (system), messages[-1] (current turn)
            # Find first removable pair
            removed = False
            for i in range(1, len(messages) - 1):
                if messages[i]["role"] == "user" and i + 1 < len(messages) - 1 and messages[i + 1]["role"] == "assistant":
                    messages.pop(i)
                    messages.pop(i)  # the assistant message shifted to index i
                    removed = True
                    break
            if not removed:
                break
            total = self._estimate_tokens(messages)

        return messages

    @staticmethod
    def _estimate_tokens(messages: list[dict]) -> int:
        """Conservative token estimate (Korean ≈ 3 chars per token)."""
        total_chars = sum(len(m.get("content", "")) for m in messages)
        return total_chars // 3
