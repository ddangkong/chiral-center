"""AutoGen 패턴: LLM 기반 동적 발언 순서 선택."""

import json
import random
import logging
from typing import Optional

from llm.base import BaseLLMClient
from models.persona import PersonaProfile

logger = logging.getLogger(__name__)


class SpeakerSelector:
    """LLM이 다음 발언자를 결정. fallback은 random.shuffle."""

    def __init__(self, llm: BaseLLMClient):
        self.llm = llm

    async def select_speakers(
        self,
        personas: list[PersonaProfile],
        recent_discussion: str,
        brief_text: str,
        round_num: int,
        max_speakers: int = 4,
    ) -> list[PersonaProfile]:
        """이번 라운드의 발언 순서를 결정."""
        if not personas:
            return []

        names = [f"{p.name}({p.role})" for p in personas]

        prompt = f"""회의 라운드 {round_num}에서 누가 발언해야 할지 결정하세요.

참여자: {', '.join(names)}

{brief_text}

최근 토론:
{recent_discussion[-1500:] if recent_discussion else '(아직 없음)'}

발언 순서 결정 기준:
1. 직전 라운드에서 언급되거나 반박당한 사람이 우선 (반박권)
2. 미답변 질문이 있는 사람이 우선
3. 아직 발언하지 않은 사람이 우선
4. 해당 쟁점의 전문가가 우선
5. 모든 사람이 매 라운드 발언할 필요 없음 (관련 없으면 skip 가능)

{max_speakers}명 이하로 선택하세요.

JSON: {{"speakers": ["이름1", "이름2", ...], "reasoning": "선택 이유"}}"""

        try:
            response = await self.llm.complete(
                [
                    {"role": "system", "content": "회의 발언 순서를 결정합니다. 관련성 높은 참여자부터 배치. JSON만 응답."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=512,
            )
            data = self._parse_json(response)
            selected_names = data.get("speakers", [])

            # 이름으로 PersonaProfile 매칭
            ordered = []
            for name in selected_names:
                for p in personas:
                    if p.name in name or name in p.name:
                        if p not in ordered:
                            ordered.append(p)
                            break

            if ordered:
                logger.info(f"speaker_selected round={round_num} speakers={[p.name for p in ordered]} reason={data.get('reasoning','')[:80]}")
                return ordered[:max_speakers]
        except Exception as e:
            logger.error(f"Speaker selection error: {e}")

        # Fallback: random shuffle
        shuffled = list(personas)
        random.shuffle(shuffled)
        return shuffled[:max_speakers]

    def _parse_json(self, text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)
