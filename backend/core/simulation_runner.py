"""Multi-agent discussion simulation engine."""
import json
import re
import uuid
import asyncio
import random
from datetime import datetime
from typing import AsyncGenerator, Optional

from llm.base import BaseLLMClient
from models.persona import PersonaProfile
from models.simulation import SimConfig, SimEvent, SimResult, SimStatus
from core.db_indexer import db_indexer
from core.agent_context import ConversationManager
from core.discussion_memory import DiscussionMemoryManager, DiscussionEvent
from core.discussion_state import DiscussionStateTracker
from core.speaker_selector import SpeakerSelector
from core.fixed_roles import (
    create_fixed_role_agents, _needs_data_support, _is_price_request,
    DB_AGENT_PROMPT_V2, PRICE_RESEARCH_PROMPT, MODERATOR_PROMPT_V2,
    DEVILS_ADVOCATE_PROMPT,
)
from utils.logger import log


DISCUSSION_ROLE_ALIASES: dict[str, set[str]] = {
    "market_analyst": {
        "market_analyst",
        "market analyst",
        "마케팅팀장",
        "영업팀장",
    },
    "financial_analyst": {
        "financial_analyst",
        "financial analyst",
        "재무팀장",
    },
    "tech_reviewer": {
        "tech_reviewer",
        "technical reviewer",
        "r&d팀장",
        "r&d",
    },
    "risk_analyst": {
        "risk_analyst",
        "risk analyst",
        "scm팀장",
        "구매팀장",
        "품질관리팀장",
    },
    "strategy_lead": {
        "strategy_lead",
        "strategy lead",
        "기획팀장",
    },
    "devils_advocate": {
        "devils_advocate",
        "devil's advocate",
        "devils advocate",
    },
}


def _normalize_role_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


DISCUSSION_MIN_CHARS = 1500
DISCUSSION_TARGET_RANGE = "1500-2200자"
LENGTH_REWRITE_ATTEMPTS = 4
TURN_GENERATION_ATTEMPTS = 3
PLACEHOLDER_REWRITE_ATTEMPTS = 3


# 발언 안에서 LLM이 자주 흘리는 placeholder/빈 수치 패턴.
# 사용자 보고: "수치가 -0.? 수준 처럼 빈 데이터로 들어가는데도 답변에 계속 활용함"
# 다음 패턴 중 하나라도 검출되면 발언을 무효화하고 LLM에 재작성을 요청한다.
_PLACEHOLDER_NUMBER_PATTERNS = [
    re.compile(r"-\s*0\s*\.\s*\?"),                                  # -0.? / -0 . ?
    re.compile(r"(?<![0-9])\?\s*\.\s*\?(?:\s*%)?"),                  # ?.? / ?.?%
    re.compile(r"(?<![0-9A-Za-z])X{1,3}\s*[.,]?\s*X{0,3}\s*%"),       # XX% / X.X%
    re.compile(r"(?<![0-9A-Za-z])X{2,3}\s*억"),                       # XX억
    re.compile(r"\bN\s*/\s*A\s*%"),                                  # N/A%
    re.compile(r"\bTBD\b", re.IGNORECASE),                            # TBD
    re.compile(r"(?<![0-9])\?{2,}\s*%?"),                            # ??%, ???
    re.compile(r"-\s*0\s*\.\s*0+\s*%(?!\d)"),                        # -0.0%, -0.00%
    re.compile(r"약\s*0\s*%"),                                        # 약 0%
    re.compile(r"거의\s*0(?:\s*에\s*가까운)?"),                        # 거의 0 / 거의 0에 가까운
    re.compile(r"마이너스\s*0\s*\.\s*\?"),                            # 마이너스 0.?
    re.compile(r"데이터\s*미확인\s*%"),                                # 데이터 미확인%
    re.compile(r"추후\s*확인\s*%"),                                    # 추후 확인%
]


def _find_placeholder_numbers(text: str) -> list[str]:
    """발언에서 placeholder/빈 수치 표기를 찾아 리스트로 반환. 없으면 빈 리스트."""
    if not text:
        return []
    found: list[str] = []
    for pat in _PLACEHOLDER_NUMBER_PATTERNS:
        for m in pat.finditer(text):
            snippet = m.group(0).strip()
            if snippet and snippet not in found:
                found.append(snippet)
    return found


TWITTER_PROMPT = """당신은 {name}, {role}입니다.
성격: {personality}
우리 부서 입장: {stance}
부서 목표: {goals}

=== 참고 자료 (지식 그래프 기반) ===
전문 분야: {knowledge}
{relationships_context}
{ontology_context}
=== 참고 자료 끝 ===

안건: {topic}

최근 발언:
{recent_posts}

[행동 규칙]
- 반드시 당신 부서의 이해관계와 전문성에서 발언하세요
- 구체적 수치, 사례, 근거를 들어 주장하세요
- 다른 부서 발언에 동의하거나 반박할 때도 우리 부서 관점에서 하세요
- 예: 마케팅 → "소비자 조사 결과...", SCM → "현재 리드타임 기준으로...", R&D → "기술적으로 봤을 때..."
- 화면이 Twitter 형식처럼 보여도 실제 280자 제한은 적용하지 말고 최소 1500자 이상 작성하세요
- 절대 금지: "시뮬레이션", "AI", "연습", "역할극" 등 메타 발언

행동 선택 (하나만):
1. "post" - 발언 (최소 1500자, 권장 1500-2200자)
2. "reply" - 다른 발언에 답변 (target_post 포함)
3. "repost" - 공유 + 코멘트
4. "skip" - 이번 라운드 패스

JSON으로 응답:
{{
  "action": "post|reply|repost|skip",
  "content": "한국어 발언 (최소 1500자, 권장 1500-2200자, 부서 관점, 구체적 근거와 수치 포함)",
  "target_post": null 또는 발언번호,
  "reasoning": "내부 판단 근거 (영어 가능)"
}}
"""

REDDIT_PROMPT = """당신은 {name}, {role}입니다.
성격: {personality}
우리 부서 입장: {stance}
부서 목표: {goals}

=== 참고 자료 (지식 그래프 기반) ===
전문 분야: {knowledge}
{relationships_context}
{ontology_context}
=== 참고 자료 끝 ===

안건: {topic}

최근 발언:
{recent_posts}

[행동 규칙]
- 반드시 당신 부서의 이해관계와 전문성에서 발언하세요
- 구체적 수치, 사례, 비용/일정 영향을 근거로 주장하세요
- 다른 부서 발언에 대해 부서 입장에서 구체적으로 동의/반박/보완하세요
- 예: 재무 → "이 안의 ROI를 계산해보면...", 구매 → "현재 공급사 단가 기준...", 품질 → "현 불량률 대비..."
- 길게 분석적으로 작성 가능 (Reddit 스타일)
- 짧은 댓글이 아니라 최소 1500자 이상, 권장 1500-2200자의 내부 전략 메모 수준으로 작성하세요
- 절대 금지: "시뮬레이션", "AI", "연습", "역할극" 등 메타 발언

행동 선택 (하나만):
1. "post" - 상세 발언 (최소 1500자, 권장 1500-2200자)
2. "reply" - 답변 (target_post 포함)
3. "repost" - 공유 + 코멘트
4. "skip" - 패스

JSON으로 응답:
{{
  "action": "post|reply|repost|skip",
  "content": "한국어 발언 (최소 1500자, 권장 1500-2200자, 부서 관점, 분석적, 근거와 수치 포함)",
  "target_post": null 또는 발언번호,
  "reasoning": "내부 판단 근거 (영어 가능)"
}}
"""

DB_AGENT_PROMPT = """You are a DB Information Agent.
During a social simulation about: {topic}

The following internal database records are relevant to the current discussion:
{db_records}

Your task:
- Summarize the most relevant data points from the records above
- Explain how this internal data relates to the current discussion
- Surface any important figures, facts, or trends the participants should know

Write a concise briefing in Korean (2-4 sentences). Be factual and data-driven.

Respond in JSON:
{{
  "briefing": "한국어 DB 브리핑 내용 (2-4문장)",
  "source_files": ["파일명1", "파일명2"]
}}
"""

MODERATOR_PROMPT = """당신은 이 안건의 회의 진행자(퍼실리테이터)입니다.

안건: {topic}

최근 발언 (최근 10건):
{recent_posts}

역할:
1. 쟁점 정리: 부서 간 의견이 갈리는 핵심 쟁점을 정리하세요
2. 팩트 체크: 각 부서 발언 중 검증이 필요한 수치나 주장을 지적하세요
3. 논의 방향: 다음 라운드에서 집중해야 할 논점을 제시하세요

간결하고 중립적으로 작성하세요.

JSON으로 응답:
{{
  "fact_check": "쟁점 정리 및 팩트 체크 (2-3문장, 한국어)",
  "roi_insight": "논의 방향 제안 (2-3문장, 한국어)"
}}
"""


class SimulationEngine:
    """Runs multi-agent social simulation."""

    def __init__(self, llm_client: BaseLLMClient):
        self.llm = llm_client
        self._simulations: dict[str, SimResult] = {}
        self._stop_flags: dict[str, bool] = {}
        self._conversation_mgr: Optional[ConversationManager] = None
        self._min_chars: int = DISCUSSION_MIN_CHARS
        self._temperature: float = 0.7

    def _lookup_prompt_override(
        self,
        persona: PersonaProfile,
        prompt_overrides: dict[str, str] | None,
    ) -> str:
        """Resolve the best matching override for a persona across legacy and fixed-role keys."""
        if not prompt_overrides:
            return ""

        normalized = {
            _normalize_role_key(key): value
            for key, value in prompt_overrides.items()
            if value and value.strip()
        }

        candidates: list[str] = [
            persona.fixed_role_id or "",
            persona.role,
            persona.name,
        ]

        if persona.fixed_role_id:
            candidates.extend(DISCUSSION_ROLE_ALIASES.get(persona.fixed_role_id, set()))

        for candidate in candidates:
            if not candidate:
                continue
            found = normalized.get(_normalize_role_key(candidate))
            if found:
                return found

        return ""

    async def _revise_json_response_for_length(
        self,
        messages: list[dict],
        data: dict,
        min_chars: int = DISCUSSION_MIN_CHARS,
        attempts: int = LENGTH_REWRITE_ATTEMPTS,
    ) -> dict:
        """Rewrite JSON content until it satisfies the minimum length or fail hard."""
        revised = data
        # Slim context: system prompt + last user turn only (avoid context overflow)
        slim_messages = [messages[0], messages[-1]]

        for attempt_num in range(1, attempts + 1):
            content = (revised.get("content") or "").strip()
            action = revised.get("action", "skip")
            if action == "skip" or len(content) >= min_chars:
                if attempt_num > 1:
                    log.info("revision_succeeded", attempt=attempt_num - 1, final_len=len(content))
                return revised

            log.warning(
                "content_too_short_revising",
                action=action,
                content_len=len(content),
                min_required=min_chars,
                attempt=f"{attempt_num}/{attempts}",
            )

            correction_messages = slim_messages + [
                {"role": "assistant", "content": json.dumps(revised, ensure_ascii=False)},
                {
                    "role": "user",
                    "content": (
                        f"[필수 재작성 — {attempt_num}차 요청] 방금 응답의 content는 {len(content)}자입니다. "
                        f"최소 {min_chars}자 필요합니다.\n\n"
                        f"재작성 규칙:\n"
                        f"1. 동일한 JSON 스키마 유지 (action, content, target_post, reasoning)\n"
                        f"2. content를 최소 {min_chars}자 이상, 권장 {DISCUSSION_TARGET_RANGE}로 확장\n"
                        f"3. 현재 논점을 3개 이상 단락으로 분리하고, 각 단락에 구체적 수치/사례/반론 포함\n"
                        f"4. reply/repost도 짧은 댓글이 아니라 심층 전략 분석 보고서 수준으로 작성\n"
                        f"5. 기존 주장을 유지하되 근거, 배경, 시사점을 대폭 보강하세요"
                    ),
                },
            ]
            try:
                response = await self.llm.complete(
                    correction_messages,
                    temperature=0.75,
                    max_tokens=3000,
                )
                revised = self._parse_json(response)
            except Exception as e:
                log.warning("revision_parse_failed", attempt=attempt_num, error=str(e))
                break

        final_content = (revised.get("content") or "").strip()
        final_action = revised.get("action", "skip")
        if final_action != "skip" and len(final_content) < min_chars:
            log.error(
                "revision_failed_all_attempts",
                final_len=len(final_content),
                min_required=min_chars,
                action=final_action,
                attempts=attempts,
            )
            raise ValueError(
                f"content shorter than minimum after {attempts} rewrites: {len(final_content)} < {min_chars}",
            )
        return revised

    async def _scrub_placeholder_numbers(
        self,
        messages: list[dict],
        data: dict,
        attempts: int = PLACEHOLDER_REWRITE_ATTEMPTS,
    ) -> dict:
        """발언 안에 placeholder/빈 수치(-0.?, ??%, XX% 등)가 있으면 재작성한다.

        길이 검증과 분리해서 호출되며, 검출 시 LLM에 정확히 어떤 토큰이
        무효인지 알려주고 동일 JSON 스키마로 재생성을 요청한다. 모든 시도가
        실패하면 마지막 응답에서 placeholder를 일괄 [수치 미확인]으로 치환해
        토론은 계속되도록 한다.
        """
        revised = data
        if revised.get("action", "skip") == "skip":
            return revised

        slim_messages = [messages[0], messages[-1]]

        for attempt_num in range(1, attempts + 1):
            content = (revised.get("content") or "").strip()
            placeholders = _find_placeholder_numbers(content)
            if not placeholders:
                if attempt_num > 1:
                    log.info(
                        "placeholder_scrub_succeeded",
                        attempt=attempt_num - 1,
                    )
                return revised

            log.warning(
                "placeholder_numbers_detected",
                placeholders=placeholders[:5],
                attempt=f"{attempt_num}/{attempts}",
            )

            placeholder_list = ", ".join(f'"{p}"' for p in placeholders[:8])
            correction_messages = slim_messages + [
                {"role": "assistant", "content": json.dumps(revised, ensure_ascii=False)},
                {
                    "role": "user",
                    "content": (
                        f"[필수 재작성 — placeholder 수치 검출] 방금 응답의 content에서 다음과 같은 "
                        f"의미 없는 placeholder/빈 수치 표기가 발견되었습니다: {placeholder_list}.\n\n"
                        f"이런 표기는 분석 가치가 0이며 절대 허용되지 않습니다. 다음 중 하나로 모두 교체하세요:\n"
                        f"1. 정확한 수치를 알면 그 수치로 (예: '8.4%', '연 4.2조원')\n"
                        f"2. 모르면 합리적 추정치 + 가정 명시 (예: '업계 평균 마진율 8% 가정 시')\n"
                        f"3. 추정도 어려우면 해당 수치 자리를 통째로 삭제하고 정성적 분석으로 대체\n"
                        f"4. 또는 data_request 필드에 어떤 데이터가 필요한지 구체적으로 적기\n\n"
                        f"동일한 JSON 스키마(action, content, target_post, reasoning)를 유지하고, "
                        f"위 placeholder 표기가 단 하나도 남지 않도록 다시 작성하세요."
                    ),
                },
            ]
            try:
                response = await self.llm.complete(
                    correction_messages,
                    temperature=0.6,
                    max_tokens=3000,
                )
                revised = self._parse_json(response)
            except Exception as e:
                log.warning("placeholder_revision_parse_failed", attempt=attempt_num, error=str(e))
                break

        # 최종 폴백: 모든 시도 실패 시 placeholder를 명시적 토큰으로 치환해 토론 진행을 막지 않는다.
        final_content = (revised.get("content") or "").strip()
        if _find_placeholder_numbers(final_content):
            log.warning("placeholder_scrub_giving_up_replacing", attempts=attempts)
            for pat in _PLACEHOLDER_NUMBER_PATTERNS:
                final_content = pat.sub("[수치 미확인]", final_content)
            revised["content"] = final_content
        return revised

    async def _scrub_placeholder_numbers_text(
        self,
        system_prompt: str,
        user_prompt: str,
        content: str,
        attempts: int = PLACEHOLDER_REWRITE_ATTEMPTS,
    ) -> str:
        """plain text 발언(devils_advocate 등) 안의 placeholder 수치를 잡아 재작성."""
        revised = content.strip()
        for attempt_num in range(1, attempts + 1):
            placeholders = _find_placeholder_numbers(revised)
            if not placeholders:
                if attempt_num > 1:
                    log.info("text_placeholder_scrub_succeeded", attempt=attempt_num - 1)
                return revised
            log.warning(
                "text_placeholder_numbers_detected",
                placeholders=placeholders[:5],
                attempt=f"{attempt_num}/{attempts}",
            )
            placeholder_list = ", ".join(f'"{p}"' for p in placeholders[:8])
            try:
                response = await self.llm.complete(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": revised},
                        {
                            "role": "user",
                            "content": (
                                f"[필수 재작성] 방금 응답에서 placeholder 수치 표기가 검출됐습니다: {placeholder_list}.\n"
                                f"이런 표기는 분석 가치가 0이며 절대 허용되지 않습니다. 정확한 수치, "
                                f"가정 명시 추정치, 또는 정성적 분석으로 대체하세요. placeholder가 단 하나도 "
                                f"남지 않게 다시 작성하세요."
                            ),
                        },
                    ],
                    temperature=0.6,
                    max_tokens=3000,
                )
                revised = response.strip()
            except Exception as e:
                log.warning("text_placeholder_revision_failed", attempt=attempt_num, error=str(e))
                break
        # 최종 폴백: 잔존 placeholder를 [수치 미확인]으로 치환
        if _find_placeholder_numbers(revised):
            log.warning("text_placeholder_giving_up_replacing", attempts=attempts)
            for pat in _PLACEHOLDER_NUMBER_PATTERNS:
                revised = pat.sub("[수치 미확인]", revised)
        return revised

    async def _revise_text_for_length(
        self,
        system_prompt: str,
        user_prompt: str,
        content: str,
        min_chars: int = DISCUSSION_MIN_CHARS,
        attempts: int = LENGTH_REWRITE_ATTEMPTS,
    ) -> str:
        """Rewrite plain text until it satisfies the minimum length or fail hard."""
        revised = content.strip()
        for attempt_num in range(1, attempts + 1):
            if len(revised) >= min_chars:
                if attempt_num > 1:
                    log.info("text_revision_succeeded", attempt=attempt_num - 1, final_len=len(revised))
                return revised
            log.warning("text_too_short_revising", content_len=len(revised), min_required=min_chars, attempt=f"{attempt_num}/{attempts}")
            try:
                response = await self.llm.complete(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": revised},
                        {
                            "role": "user",
                            "content": (
                                f"[필수 재작성 — {attempt_num}차] 방금 응답은 {len(revised)}자라서 최소 {min_chars}자 기준에 못 미칩니다.\n"
                                f"최소 {min_chars}자 이상, 권장 {DISCUSSION_TARGET_RANGE}로 확장하세요.\n"
                                "논점을 3개 이상 단락으로 나누고, 숨은 가정 분석, 반례, 실패 시나리오, 구체적 대안을 포함하세요."
                            ),
                        },
                    ],
                    temperature=0.8,
                    max_tokens=3000,
                )
                revised = response.strip()
            except Exception as e:
                log.warning("text_revision_failed", attempt=attempt_num, error=str(e))
                break
        if len(revised) < min_chars:
            raise ValueError(
                f"text shorter than minimum after rewrite: {len(revised)} < {min_chars}",
            )
        return revised

    def _length_retry_messages(self, messages: list[dict], attempt: int, min_chars: int) -> list[dict]:
        """Append a stricter retry notice when a previous generation missed the length target."""
        # Use slim context to avoid overwhelming the model
        retry_messages = [messages[0], messages[-1]]
        retry_messages.append({
            "role": "user",
            "content": (
                f"[필수 — 재시도 {attempt + 1}/{TURN_GENERATION_ATTEMPTS}] "
                f"이전 응답은 최소 길이 기준 {min_chars}자를 지키지 못했습니다.\n\n"
                f"이번에는 반드시 {min_chars}자 이상, 권장 {DISCUSSION_TARGET_RANGE} 분량으로 작성하세요.\n"
                f"- reply/repost도 짧은 댓글이 아니라 심층 분석 보고서 수준으로 작성\n"
                f"- 논점을 3개 이상 단락으로 구조화\n"
                f"- 각 단락에 구체적 수치, 기업명, 사례 포함\n"
                f"- {min_chars}자 미만은 실패 처리됩니다"
            ),
        })
        return retry_messages

    async def run_simulation(
        self,
        config: SimConfig,
        personas: list[PersonaProfile],
        project_id: Optional[str] = None,
        ontology_context: str = "",
        global_directive: str = "",
        prompt_overrides: dict[str, str] | None = None,
        disabled_roles: list[str] | None = None,
        fixed_core_agents: list[PersonaProfile] | None = None,
        fixed_support_agents: list[PersonaProfile] | None = None,
    ) -> AsyncGenerator[SimEvent, None]:
        """Run simulation and yield events as they happen (SSE-compatible)."""
        sim_id = config.id

        result = SimResult(
            id=sim_id,
            config=config,
            status=SimStatus.RUNNING,
            total_rounds=config.num_rounds,
        )
        self._simulations[sim_id] = result
        self._stop_flags[sim_id] = False

        log.info("simulation_start", sim_id=sim_id,
                 personas=len(personas), rounds=config.num_rounds)

        # Initialize per-agent conversation context manager
        self._conversation_mgr = ConversationManager(
            llm=self.llm,
            max_history_turns=6,
            max_input_tokens=3000,
        )

        # Post history for context
        post_history: list[dict] = []

        try:
            # Discussion 모드면 새 엔진으로 분기
            if config.platform == "discussion":
                async for event in self._run_discussion_mode(
                    config, personas, result, post_history,
                    ontology_context, global_directive, prompt_overrides or {},
                    project_id,
                    disabled_roles=disabled_roles or [],
                    fixed_core_agents=fixed_core_agents,
                    fixed_support_agents=fixed_support_agents,
                ):
                    yield event
                return

            for round_num in range(1, config.num_rounds + 1):
                if self._stop_flags.get(sim_id, False):
                    log.info("simulation_stopped", sim_id=sim_id, round=round_num)
                    result.status = SimStatus.PAUSED
                    break

                result.current_round = round_num
                log.info("simulation_round", sim_id=sim_id, round=round_num)

                # Check for injection events at this round
                for injection in config.injection_events:
                    if injection.get("round") == round_num:
                        inject_event = SimEvent(
                            round_num=round_num,
                            timestamp=datetime.now().isoformat(),
                            persona_id="__system__",
                            persona_name="[System Event]",
                            action_type="injection",
                            content=injection.get("content", ""),
                            metadata={"injection": True},
                        )
                        result.events.append(inject_event)
                        post_history.append({
                            "post_num": len(post_history) + 1,
                            "author": "[Breaking News]",
                            "content": injection["content"],
                            "type": "injection",
                        })
                        yield inject_event

                # Each persona acts once per round (shuffled order)
                acting_order = list(personas)
                random.shuffle(acting_order)

                for persona in acting_order:
                    if self._stop_flags.get(sim_id, False):
                        break

                    event = await self._agent_act(
                        persona, config.topic, post_history, round_num,
                        total_rounds=config.num_rounds,
                        platform=config.platform,
                        ontology_context=ontology_context,
                        global_directive=global_directive,
                        prompt_overrides=prompt_overrides or {},
                    )

                    if event and event.action_type != "skip":
                        result.events.append(event)
                        post_history.append({
                            "post_num": len(post_history) + 1,
                            "author": persona.name,
                            "content": event.content,
                            "type": event.action_type,
                            "target": event.target_id,
                        })
                        yield event

                    # Small delay to avoid rate limiting
                    await asyncio.sleep(0.05)

                # 모더레이터: 매 2라운드마다 팩트체크 + ROI 인사이트
                if round_num % 2 == 0 and post_history:
                    moderator_event = await self._moderator_act(
                        config.topic, post_history, round_num
                    )
                    if moderator_event:
                        result.events.append(moderator_event)
                        yield moderator_event

                # DB 에이전트: project_id가 있고 DB 인덱스가 있으면 매 라운드 검색
                if project_id and db_indexer.record_count(project_id) > 0:
                    db_event = await self._db_agent_act(
                        config.topic, post_history, round_num, project_id
                    )
                    if db_event:
                        result.events.append(db_event)
                        yield db_event

            if result.status != SimStatus.PAUSED:
                result.status = SimStatus.COMPLETED

            log.info("simulation_complete", sim_id=sim_id,
                     total_events=len(result.events))

        except Exception as e:
            result.status = SimStatus.ERROR
            log.error("simulation_error", sim_id=sim_id, error=str(e))
            raise

    async def _agent_act(
        self,
        persona: PersonaProfile,
        topic: str,
        post_history: list[dict],
        round_num: int,
        total_rounds: int = 10,
        platform: str = "discussion",
        ontology_context: str = "",
        global_directive: str = "",
        prompt_overrides: dict[str, str] | None = None,
    ) -> Optional[SimEvent]:
        """Have a single agent decide and execute an action (multi-turn context)."""
        role_override = self._lookup_prompt_override(persona, prompt_overrides)

        base_messages = self._conversation_mgr.build_messages(
            persona=persona,
            topic=topic,
            post_history=post_history,
            round_num=round_num,
            total_rounds=total_rounds,
            platform=platform,
            ontology_context=ontology_context,
            global_directive=global_directive,
            role_override=role_override,
        )

        last_error = None
        for attempt in range(TURN_GENERATION_ATTEMPTS):
            messages = (
                self._length_retry_messages(base_messages, attempt, DISCUSSION_MIN_CHARS)
                if attempt > 0 else list(base_messages)
            )
            try:
                response = await self.llm.complete(messages, temperature=0.8, max_tokens=3000)
                data = self._parse_json(response)
                if platform in {"twitter", "reddit", "discussion"}:
                    data = await self._revise_json_response_for_length(base_messages, data)
                    data = await self._scrub_placeholder_numbers(base_messages, data)
                    response = json.dumps(data, ensure_ascii=False)

                # Record this turn for future context
                self._conversation_mgr.record_response(
                    persona.id, base_messages[-1]["content"], response, round_num,
                )

                # Consolidate memory if history exceeds window
                ctx = self._conversation_mgr.get_or_create(persona.id)
                if ctx.turns_count > self._conversation_mgr.max_history_turns:
                    await self._conversation_mgr.consolidate_memory(persona)

                action_type = data.get("action", "skip")
                content = data.get("content", "")
                target = data.get("target_post")

                if action_type == "skip":
                    return SimEvent(
                        round_num=round_num,
                        timestamp=datetime.now().isoformat(),
                        persona_id=persona.id,
                        persona_name=persona.name,
                        action_type="skip",
                    )

                return SimEvent(
                    round_num=round_num,
                    timestamp=datetime.now().isoformat(),
                    persona_id=persona.id,
                    persona_name=persona.name,
                    action_type=action_type,
                    content=content,
                    target_id=str(target) if target else None,
                    metadata={
                        "reasoning": data.get("reasoning", ""),
                    },
                )
            except Exception as e:
                last_error = e

        log.warning("agent_action_error", persona=persona.name, error=str(last_error))
        return None

    async def _moderator_act(
        self,
        topic: str,
        post_history: list[dict],
        round_num: int,
    ) -> Optional[SimEvent]:
        """Moderator interjects with fact-check and ROI insight."""
        recent = post_history[-10:] if post_history else []
        recent_text = "\n".join(
            f"[#{p['post_num']}] @{p['author']}: {p['content']}"
            for p in recent
        )

        prompt = MODERATOR_PROMPT.format(topic=topic, recent_posts=recent_text)

        try:
            response = await self.llm.complete([
                {"role": "system", "content": "You are an expert analyst and fact-checker. Respond with valid JSON only."},
                {"role": "user", "content": prompt},
            ], temperature=0.3, max_tokens=512)

            data = self._parse_json(response)
            content = f"[팩트체크] {data.get('fact_check', '')}  [ROI] {data.get('roi_insight', '')}"

            return SimEvent(
                round_num=round_num,
                timestamp=datetime.now().isoformat(),
                persona_id="__moderator__",
                persona_name="⚖️ Moderator",
                action_type="moderator",
                content=content,
                metadata={"fact_check": data.get("fact_check", ""), "roi_insight": data.get("roi_insight", "")},
            )
        except Exception as e:
            log.warning("moderator_act_error", error=str(e))
            return None

    async def _db_agent_act(
        self,
        topic: str,
        post_history: list[dict],
        round_num: int,
        project_id: str,
    ) -> Optional[SimEvent]:
        """내부 DB에서 현재 토론과 관련된 정보를 검색해 브리핑."""
        # 최근 3개 포스트 내용을 검색 쿼리로 사용
        recent = post_history[-3:] if post_history else []
        query = topic + " " + " ".join(p["content"] for p in recent)
        query = query[:500]

        try:
            results = await db_indexer.search(project_id, query, top_k=4, threshold=0.2)
            if not results:
                return None

            db_records = "\n".join(
                f"[{r['file']}] {r['text']}" for r in results
            )
            prompt = DB_AGENT_PROMPT.format(topic=topic, db_records=db_records)

            response = await self.llm.complete([
                {"role": "system", "content": "You are a database information agent. Respond with valid JSON only. All 'briefing' values must be in Korean."},
                {"role": "user", "content": prompt},
            ], temperature=0.2, max_tokens=400)

            data = self._parse_json(response)
            briefing = data.get("briefing", "")
            sources = data.get("source_files", [r["file"] for r in results])
            source_str = ", ".join(set(sources)) if sources else ""

            content = f"[DB 데이터] {briefing}"
            if source_str:
                content += f"\n📁 출처: {source_str}"

            return SimEvent(
                round_num=round_num,
                timestamp=datetime.now().isoformat(),
                persona_id="__db_agent__",
                persona_name="🗄️ DB Agent",
                action_type="db_briefing",
                content=content,
                metadata={
                    "briefing": briefing,
                    "sources": sources,
                    "db_records": [r["text"][:100] for r in results],
                },
            )
        except Exception as e:
            log.warning("db_agent_act_error", error=str(e))
            return None

    def stop_simulation(self, sim_id: str):
        """Signal a running simulation to stop."""
        self._stop_flags[sim_id] = True

    def get_simulation(self, sim_id: str) -> Optional[SimResult]:
        return self._simulations.get(sim_id)

    def get_all_simulations(self) -> list[SimResult]:
        return list(self._simulations.values())

    def _parse_json(self, text: str) -> dict:
        """Parse JSON from LLM response, handling markdown code fences."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)

    # =====================================================================
    # Discussion Mode Engine (TinyTroupe/AutoGen inspired)
    # =====================================================================

    async def _run_discussion_mode(
        self,
        config: SimConfig,
        personas: list[PersonaProfile],
        result: SimResult,
        post_history: list[dict],
        ontology_context: str,
        global_directive: str,
        prompt_overrides: dict[str, str],
        project_id: Optional[str] = None,
        disabled_roles: list[str] | None = None,
        fixed_core_agents: list[PersonaProfile] | None = None,
        fixed_support_agents: list[PersonaProfile] | None = None,
    ) -> AsyncGenerator[SimEvent, None]:
        """2-Tier 전략 토론 모드. 고정역할 5명 + 지원 에이전트 4명."""

        memory_mgr = DiscussionMemoryManager(self.llm, reflection_interval=3)
        state_tracker = DiscussionStateTracker(self.llm)
        sim_id = config.id

        # 풀 컨텍스트 ConversationManager
        self._conversation_mgr = ConversationManager(
            llm=self.llm,
            max_history_turns=10,
            max_input_tokens=6000,
            full_context_mode=True,  # 토론 끝까지 전체 컨텍스트 유지
        )

        # 고정 역할 에이전트: 호출자(simulation.py /run)가 넘겨준 동일 인스턴스를 사용.
        # 이렇게 해야 프론트의 start broadcast와 실제 speaker id가 일치한다.
        if fixed_core_agents is not None or fixed_support_agents is not None:
            core_agents = list(fixed_core_agents or [])
            support_agents = list(fixed_support_agents or [])
        else:
            # 호환성: 직접 호출되는 경우 내부에서 생성 (단위 테스트/레거시 경로)
            core_agents, support_agents = create_fixed_role_agents(
                topic=config.topic,
                ontology_context=ontology_context,
            )
            disabled = {_normalize_role_key(role) for role in (disabled_roles or []) if role}
            if disabled:
                core_agents = [
                    agent for agent in core_agents
                    if _normalize_role_key(agent.fixed_role_id or "") not in disabled
                    and _normalize_role_key(agent.role) not in disabled
                ]
                support_agents = [
                    agent for agent in support_agents
                    if _normalize_role_key(agent.fixed_role_id or "") not in disabled
                    and _normalize_role_key(agent.role) not in disabled
                ]

        # 지원 에이전트 매핑 (support_agents가 필터링된 후의 결과를 참조)
        devils_advocate = next((a for a in support_agents if a.fixed_role_id == "devils_advocate"), None)
        moderator_enabled = any(a.fixed_role_id == "moderator" for a in support_agents)
        db_agent_enabled = any(a.fixed_role_id == "db_agent" for a in support_agents)
        price_research_enabled = any(a.fixed_role_id == "price_research" for a in support_agents)
        all_personas = core_agents + support_agents

        moderator_feedback = ""

        # 시작 이벤트: 참여 에이전트 목록
        log.info("discussion_v2_start", sim_id=sim_id,
                 core_agents=[a.name for a in core_agents],
                 support_agents=[a.name for a in support_agents])

        for round_num in range(1, config.num_rounds + 1):
            if self._stop_flags.get(sim_id, False):
                result.status = SimStatus.PAUSED
                break

            result.current_round = round_num
            log.info("discussion_round", sim_id=sim_id, round=round_num)

            # ── 1. 인젝션 이벤트 ──
            for injection in config.injection_events:
                if injection.get("round") == round_num:
                    inject_event = SimEvent(
                        round_num=round_num,
                        timestamp=datetime.now().isoformat(),
                        persona_id="__system__",
                        persona_name="[시스템]",
                        action_type="injection",
                        content=injection.get("content", ""),
                    )
                    result.events.append(inject_event)
                    post_history.append({
                        "post_num": len(post_history) + 1,
                        "author": "[속보]",
                        "content": injection["content"],
                        "type": "injection",
                    })
                    yield inject_event

            brief_text = state_tracker.format_brief_for_prompt()
            round_events: list[DiscussionEvent] = []

            # ── 2. 고정역할 + 엔티티 + 커스텀 에이전트 전원 발언 (순서 랜덤 셔플) ──
            extra_agents = [p for p in personas if getattr(p, 'agent_tier', '') in ('entity', 'dynamic')]
            speaking_order = list(core_agents) + extra_agents
            random.shuffle(speaking_order)

            for persona in speaking_order:
                if self._stop_flags.get(sim_id, False):
                    break

                # 메모리 주입
                agent_memory = memory_mgr.get_agent_memory(persona.id, max_recent=8)
                self._conversation_mgr.inject_memory_context(agent_memory)
                self._conversation_mgr.inject_discussion_brief(brief_text)
                self._conversation_mgr.inject_moderator_feedback(moderator_feedback)

                event = await self._discussion_agent_act(
                    persona, config.topic, post_history, round_num,
                    total_rounds=config.num_rounds,
                    ontology_context=ontology_context,
                    global_directive=global_directive,
                    prompt_overrides=prompt_overrides,
                )

                if event and event.action_type != "skip":
                    result.events.append(event)
                    post_history.append({
                        "post_num": len(post_history) + 1,
                        "author": persona.name,
                        "content": event.content,
                        "type": event.action_type,
                        "target": event.target_id,
                    })

                    disc_event = DiscussionEvent(
                        event_id=event.event_id,
                        round_num=round_num,
                        speaker_id=persona.id,
                        speaker_name=persona.name,
                        speaker_role=persona.role,
                        action_type=event.action_type,
                        content=event.content,
                        target_id=event.target_id,
                        thread_id=event.thread_id,
                        parent_event_id=event.parent_event_id,
                    )
                    memory_mgr.record_event(disc_event)
                    state_tracker.record_event(disc_event)
                    round_events.append(disc_event)
                    yield event

                    # ── 2a. 데이터 요청 자동 감지 → 지원 에이전트 호출 ──
                    # db_agent(일반) 또는 price_research(가격)가 켜져 있어야 호출.
                    data_req = event.data_request or event.metadata.get("data_request")
                    should_invoke_data_agent = (
                        _needs_data_support(event.content, data_req)
                        and project_id
                        and (db_agent_enabled or price_research_enabled)
                    )
                    if should_invoke_data_agent:
                        is_price = _is_price_request(event.content, data_req)
                        # 가격 요청이지만 price_research가 꺼진 경우: db_agent로 폴백
                        if is_price and not price_research_enabled:
                            is_price = False if db_agent_enabled else None
                        # 일반 요청인데 db_agent가 꺼진 경우: 스킵
                        elif not is_price and not db_agent_enabled:
                            is_price = None
                        if is_price is not None:
                            query = data_req or event.content[:300]
                            db_response = await self._process_data_request(
                                request_text=query,
                                requesting_agent=persona.name,
                                topic=config.topic,
                                project_id=project_id,
                                round_num=round_num,
                                is_price=is_price,
                            )
                            if db_response:
                                result.events.append(db_response)
                                post_history.append({
                                    "post_num": len(post_history) + 1,
                                    "author": db_response.persona_name,
                                    "content": db_response.content,
                                    "type": db_response.action_type,
                                    "target": None,
                                })
                                yield db_response

                await asyncio.sleep(0.05)

            # ── 3. 악마의 변호인 발언 (매 라운드 필수) ──
            if devils_advocate and round_events:
                da_event = await self._devils_advocate_act(
                    devils_advocate, config.topic, post_history,
                    round_num, round_events,
                    global_directive=global_directive,
                    prompt_overrides=prompt_overrides,
                )
                if da_event:
                    result.events.append(da_event)
                    post_history.append({
                        "post_num": len(post_history) + 1,
                        "author": da_event.persona_name,
                        "content": da_event.content,
                        "type": da_event.action_type,
                        "target": None,
                    })
                    disc_event = DiscussionEvent(
                        event_id=da_event.event_id,
                        round_num=round_num,
                        speaker_id=da_event.persona_id,
                        speaker_name=da_event.persona_name,
                        speaker_role="Devil's Advocate",
                        action_type=da_event.action_type,
                        content=da_event.content,
                    )
                    memory_mgr.record_event(disc_event)
                    state_tracker.record_event(disc_event)
                    round_events.append(disc_event)
                    yield da_event

            # ── 4. 진행자 발언 (매 라운드, 단 moderator가 활성화된 경우만) ──
            if moderator_enabled:
                mod_event = await self._moderator_act_v2(
                    config.topic, post_history, round_num, config.num_rounds,
                    state_tracker,
                )
                if mod_event:
                    result.events.append(mod_event)
                    moderator_feedback = mod_event.content
                    yield mod_event

            # ── 5. 라운드 브리프 생성 ──
            brief = await state_tracker.generate_brief(round_num, round_events)
            log.info("discussion_brief", round=round_num,
                     agreed=len(brief.agreed_facts), disputes=len(brief.open_disputes))

            # ── 6. 주기적 메모리 반영 ──
            await memory_mgr.maybe_reflect(round_num)

        if result.status != SimStatus.PAUSED:
            result.status = SimStatus.COMPLETED
        log.info("discussion_v2_complete", sim_id=sim_id, events=len(result.events))

    # ── 지원 에이전트 메서드 (V2) ────────────────────────────────────

    async def _process_data_request(
        self,
        request_text: str,
        requesting_agent: str,
        topic: str,
        project_id: str,
        round_num: int,
        is_price: bool = False,
    ) -> Optional[SimEvent]:
        """데이터 요청 처리: 에이전트 발언에서 감지된 데이터 필요성에 응답."""
        try:
            results = await db_indexer.search(project_id, request_text, top_k=6, threshold=0.15)
            if not results:
                return None

            db_records = "\n".join(f"[{r['file']}] {r['text']}" for r in results)
            prompt_template = PRICE_RESEARCH_PROMPT if is_price else DB_AGENT_PROMPT_V2
            prompt = prompt_template.format(
                requesting_agent=requesting_agent,
                data_request=request_text,
                db_records=db_records,
            )

            agent_name = "📊 시장가격 조사" if is_price else "🗄️ 데이터 브리핑"
            agent_id = "__price_research__" if is_price else "__db_agent__"

            response = await self.llm.complete([
                {"role": "system", "content": f"당신은 {agent_name} 에이전트입니다. 요청받은 데이터를 내부 DB에서 검색하여 정확한 팩트 기반 브리핑을 제공합니다. JSON으로만 응답하세요."},
                {"role": "user", "content": prompt},
            ], temperature=0.2, max_tokens=600)

            data = self._parse_json(response)
            briefing = data.get("briefing", "")
            coverage = data.get("coverage", "partial")
            sources = data.get("source_files", [r["file"] for r in results])
            missing = data.get("missing_data")

            content = f"[{requesting_agent} 요청 응답] {briefing}"
            if sources:
                content += f"\n📁 출처: {', '.join(set(sources))}"
            if coverage != "complete" and missing:
                content += f"\n⚠️ 미확인: {missing}"

            return SimEvent(
                round_num=round_num,
                timestamp=datetime.now().isoformat(),
                persona_id=agent_id,
                persona_name=agent_name,
                action_type="data_request_response",
                content=content,
                metadata={
                    "requesting_agent": requesting_agent,
                    "coverage": coverage,
                    "sources": sources,
                    "missing_data": missing,
                },
            )
        except Exception as e:
            log.warning("data_request_error", error=str(e), agent=requesting_agent)
            return None

    async def _devils_advocate_act(
        self,
        persona: PersonaProfile,
        topic: str,
        post_history: list[dict],
        round_num: int,
        round_events: list[DiscussionEvent],
        global_directive: str = "",
        prompt_overrides: dict[str, str] | None = None,
    ) -> Optional[SimEvent]:
        """악마의 변호인: 이번 라운드 발언에 대해 체계적 반론."""
        if not round_events:
            return None

        # 이번 라운드 발언 요약
        round_text = "\n".join(
            f"[{e.speaker_name}({e.speaker_role})] [{e.action_type}]: {e.content}"
            for e in round_events
        )

        prompt = f"""안건: {topic}
라운드 {round_num}의 발언들:

{round_text}

위 발언들 중 가장 강한 합의점이나 가장 대담한 제안을 찾아 체계적으로 반론을 제기하세요.
반드시 1500자 이상 작성하세요. 권장 분량은 1500-2200자입니다."""

        try:
            system_prompt = persona.strategic_framework
            role_override = self._lookup_prompt_override(persona, prompt_overrides)
            if global_directive:
                system_prompt += f"\n\n[Additional Directive]\n{global_directive}"
            if role_override:
                system_prompt += f"\n\n[Role-specific Directive]\n{role_override}"

            response = await self.llm.complete([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ], temperature=0.8, max_tokens=3000)

            content = response.strip()
            # JSON 파싱 시도, 실패하면 raw text 사용
            try:
                data = self._parse_json(response)
                content = data.get("content", content)
            except (json.JSONDecodeError, Exception):
                pass
            content = await self._revise_text_for_length(system_prompt, prompt, content)
            content = await self._scrub_placeholder_numbers_text(system_prompt, prompt, content)

            return SimEvent(
                round_num=round_num,
                timestamp=datetime.now().isoformat(),
                persona_id=persona.id,
                persona_name="😈 악마의 변호인",
                action_type="devils_advocate",
                content=content,
                metadata={"platform": "discussion"},
            )
        except Exception as e:
            log.error("devils_advocate_error", error=str(e))
            return None

    async def _moderator_act_v2(
        self,
        topic: str,
        post_history: list[dict],
        round_num: int,
        total_rounds: int,
        state_tracker: DiscussionStateTracker,
    ) -> Optional[SimEvent]:
        """V2 진행자: 고정역할 + 악마의 변호인 결과 종합."""
        if not post_history:
            return None

        recent = post_history[-25:]
        recent_text = "\n".join(
            f"[#{p['post_num']}] @{p['author']} [{p.get('type','post')}]: {p['content']}"
            for p in recent
        )
        brief = state_tracker.format_brief_for_prompt()

        prompt = MODERATOR_PROMPT_V2.format(
            topic=topic,
            round_num=round_num,
            total_rounds=total_rounds,
            brief=brief,
            recent_posts=recent_text,
        )

        try:
            response = await self.llm.complete([
                {"role": "system", "content": "전략 회의 퍼실리테이터. 중립적이고 구체적으로 진행 상황을 정리합니다."},
                {"role": "user", "content": prompt},
            ], temperature=0.3, max_tokens=800)

            content = response.strip()
            if state_tracker.current_brief:
                state_tracker.current_brief.moderator_feedback = content

            return SimEvent(
                round_num=round_num,
                timestamp=datetime.now().isoformat(),
                persona_id="__moderator__",
                persona_name="⚖️ 진행자",
                action_type="moderator",
                content=content,
                metadata={"platform": "discussion"},
            )
        except Exception as e:
            log.error("moderator_v2_error", error=str(e))
            return None

    async def _discussion_agent_act(
        self,
        persona: PersonaProfile,
        topic: str,
        post_history: list[dict],
        round_num: int,
        total_rounds: int,
        ontology_context: str = "",
        global_directive: str = "",
        prompt_overrides: dict[str, str] = {},
    ) -> Optional[SimEvent]:
        """Discussion 모드 에이전트 행동. 확장된 액션 + 긴 발언."""
        role_override = self._lookup_prompt_override(persona, prompt_overrides)

        base_messages = self._conversation_mgr.build_messages(
            persona=persona,
            topic=topic,
            post_history=post_history,
            round_num=round_num,
            total_rounds=total_rounds,
            platform="discussion",
            ontology_context=ontology_context,
            global_directive=global_directive,
            role_override=role_override,
        )

        # 글자수 옵션에 따라 프롬프트 내 하드코딩된 1500자를 동적 교체
        if self._min_chars != DISCUSSION_MIN_CHARS:
            target_range = f"{self._min_chars}-{self._min_chars + 200}자"
            for i, msg in enumerate(base_messages):
                if msg.get("content"):
                    base_messages[i] = dict(msg)
                    base_messages[i]["content"] = (
                        msg["content"]
                        .replace("최소 1500자", f"최소 {self._min_chars}자")
                        .replace("1500-2200자", target_range)
                        .replace("1500자 이상", f"{self._min_chars}자 이상")
                    )

        last_error = None
        for attempt in range(TURN_GENERATION_ATTEMPTS):
            messages = (
                self._length_retry_messages(base_messages, attempt, self._min_chars)
                if attempt > 0 else list(base_messages)
            )
            try:
                response = await self.llm.complete(
                    messages,
                    temperature=self._temperature,
                    max_tokens=3000,
                )

                data = self._parse_json(response)
                data = await self._revise_json_response_for_length(base_messages, data, min_chars=self._min_chars)
                data = await self._scrub_placeholder_numbers(base_messages, data)
                action = data.get("action", "skip")
                content = data.get("content", "")
                target = data.get("target_post")
                reasoning = data.get("reasoning", "")
                data_request = data.get("data_request")

                valid_actions = {"post", "reply", "question", "concede", "propose", "cite", "skip"}
                if action not in valid_actions:
                    action = "post"

                target_id = None
                parent_event_id = None
                thread_id = None
                if target and action in ("reply", "question", "concede", "cite"):
                    try:
                        idx = int(target) - 1
                        if 0 <= idx < len(post_history):
                            target_id = str(target)
                    except (ValueError, TypeError):
                        pass

                ctx = self._conversation_mgr.get_or_create(persona.id)
                ctx.history_pairs.append({
                    "user": f"라운드 {round_num} 토론",
                    "assistant": content[:1500],
                    "round": round_num,
                })
                ctx.turns_count += 1

                metadata = {"reasoning": reasoning, "platform": "discussion"}
                if data_request:
                    metadata["data_request"] = data_request

                return SimEvent(
                    round_num=round_num,
                    timestamp=datetime.now().isoformat(),
                    persona_id=persona.id,
                    persona_name=persona.name,
                    action_type=action,
                    content=content,
                    target_id=target_id,
                    thread_id=thread_id,
                    parent_event_id=parent_event_id,
                    data_request=data_request,
                    metadata=metadata,
                )
            except Exception as e:
                last_error = e

        log.error("discussion_agent_error", persona=persona.name, error=str(last_error))
        return None

    async def _moderator_act_discussion(
        self,
        topic: str,
        post_history: list[dict],
        round_num: int,
        state_tracker: DiscussionStateTracker,
    ) -> Optional[SimEvent]:
        """Discussion 모드 모더레이터. 피드백이 다음 라운드에 주입됨."""
        if not post_history:
            return None

        recent = post_history[-20:]
        recent_text = "\n".join(
            f"[#{p['post_num']}] @{p['author']} [{p.get('type','post')}]: {p['content']}"
            for p in recent
        )

        brief = state_tracker.format_brief_for_prompt()

        prompt = f"""당신은 전략 회의의 퍼실리테이터입니다.

안건: {topic}
라운드: {round_num}

{brief}

최근 토론:
{recent_text}

역할:
1. 이번 라운드의 핵심 진전 사항 정리 (합의된 것, 새로 제기된 것)
2. 팩트 체크: 검증이 필요한 수치나 주장 지적
3. 다음 라운드 방향 제시: 어떤 미해결 쟁점에 집중해야 하는지
4. 특정 참여자에게 질문이나 데이터 요청이 필요하면 명시

간결하지만 구체적으로 작성. 참여자 이름을 직접 언급하세요.
5-8문장."""

        try:
            response = await self.llm.complete(
                [
                    {"role": "system", "content": "전략 회의 퍼실리테이터. 중립적이고 구체적으로 진행 상황을 정리합니다."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=800,
            )

            content = response.strip()

            # 브리프에 모더레이터 피드백 기록
            if state_tracker.current_brief:
                state_tracker.current_brief.moderator_feedback = content

            return SimEvent(
                round_num=round_num,
                timestamp=datetime.now().isoformat(),
                persona_id="__moderator__",
                persona_name="⚖️ 진행자",
                action_type="moderator",
                content=content,
                metadata={"platform": "discussion"},
            )
        except Exception as e:
            log.error("discussion_moderator_error", error=str(e))
            return None
