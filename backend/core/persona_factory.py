"""Generate AI agent personas from knowledge graph entities using LLM.

Improved with TinyTroupe-inspired deep persona spec:
- Dynamic stakeholder role generation from topic (not hardcoded)
- Semantic entity-to-role assignment (not mechanical index matching)
- Rich persona profile (Big Five, communication style, beliefs, etc.)
- Meaningful inter-persona relationships via shared entity grounding
"""
import asyncio
import json
import uuid
from typing import Optional

from llm.base import BaseLLMClient
from models.ontology import OntologyResult, Entity
from models.persona import PersonaProfile, BigFiveTraits, CommunicationStyle
from utils.logger import log


# ---------------------------------------------------------------------------
# Fallback roles (used when dynamic generation fails)
# ---------------------------------------------------------------------------

FALLBACK_ROLES = [
    {"name": "마케팅팀장", "role": "Marketing Lead", "dept": "마케팅",
     "focus": "시장 트렌드, 소비자 인사이트, 브랜드 포지셔닝, 캠페인 ROI, 경쟁사 분석",
     "perspective": "시장 반응과 소비자 가치 극대화"},
    {"name": "SCM팀장", "role": "Supply Chain Manager", "dept": "공급망관리",
     "focus": "원가 구조, 조달 리드타임, 재고 최적화, 물류 효율, 공급 리스크",
     "perspective": "공급망 안정성과 원가 효율"},
    {"name": "R&D팀장", "role": "R&D Lead", "dept": "연구개발",
     "focus": "기술 feasibility, 제품 스펙, 개발 일정, 특허/IP, 품질 기준",
     "perspective": "기술적 완성도와 혁신"},
    {"name": "구매팀장", "role": "Procurement Manager", "dept": "구매",
     "focus": "원자재 가격, 공급업체 평가, 계약 조건, 원가 절감, 대체재",
     "perspective": "조달 비용 최적화"},
    {"name": "영업팀장", "role": "Sales Director", "dept": "영업",
     "focus": "매출 목표, 거래처 니즈, 가격 정책, 채널 전략, 수주 현황",
     "perspective": "매출 성장과 고객 확보"},
    {"name": "재무팀장", "role": "Finance Manager", "dept": "재무",
     "focus": "수익성 분석, 예산 배분, 투자 회수, 리스크 관리, 현금흐름",
     "perspective": "수익성과 재무 건전성"},
    {"name": "품질관리팀장", "role": "QA Manager", "dept": "품질관리",
     "focus": "품질 기준, 불량률, 인증/규격, 클레임, 공정 개선",
     "perspective": "품질 표준 준수와 리스크 방지"},
    {"name": "기획팀장", "role": "Strategy & Planning Lead", "dept": "전략기획",
     "focus": "사업 로드맵, 시장 진입 전략, KPI 설계, 경쟁 우위, 중장기 계획",
     "perspective": "중장기 전략 방향"},
]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

STAKEHOLDER_EXTRACTION_PROMPT = """다음 안건에 대해 조직 내 전략 회의에 참여할 이해관계자 역할 {count}명을 설계하세요.

안건: {topic}

관련 지식 그래프 엔티티:
{entity_context}

관련 관계:
{relation_context}

[요구사항]
- 이 안건에 특화된 역할을 생성하세요 (일반적인 부서명이 아닌, 안건과 직접 관련된 역할)
- 각 역할은 서로 상충하는 이해관계를 가져야 합니다
- 예시: 반도체 공정 안건이면 "공정 엔지니어", "수율 관리자", "장비 투자 담당" 등
- 예시: 신제품 출시 안건이면 "제품 기획자", "채널 전략가", "원가 관리자" 등

JSON 배열로 응답:
[
  {{
    "name": "한국어 역할명 (예: 공정 엔지니어)",
    "role": "English Title",
    "dept": "소속 부서/팀",
    "focus": "핵심 관심사 3~5개 (쉼표 구분)",
    "perspective": "이 안건에 대한 이 역할의 기본 입장 (한 문장)"
  }},
  ...
]
"""

PERSONA_GENERATION_PROMPT = """You are generating an organizational stakeholder for an internal strategy discussion.

Topic under discussion: {topic}

This person's organizational role:
- Title: {role_name} ({role_title})
- Department: {dept}
- Core focus areas: {focus}
- Base perspective: {perspective}

Related knowledge from the organization's knowledge graph:
{entity_context}

Generate this person's FULL profile. They must speak ENTIRELY from their department's perspective.

IMPORTANT:
- Each role has CONFLICTING priorities with other departments
- Be specific to the topic, not generic
- Include realistic departmental blind spots and biases
- Personality traits should create diverse discussion dynamics

Respond in JSON format ONLY:
{{
  "name": "{role_name}",
  "role": "{role_title}, {dept}",
  "description": "2-3 sentences about their professional background (Korean)",
  "personality": "professional traits summary (Korean, 1-2 sentences)",
  "stance": "their specific position on THIS topic (Korean, 2-3 sentences)",
  "goals": ["concrete objective 1 (Korean)", "concrete objective 2", "concrete objective 3"],
  "knowledge": ["specific domain knowledge 1", "specific domain knowledge 2", "specific domain knowledge 3"],
  "big_five": {{
    "openness": 0.0-1.0,
    "conscientiousness": 0.0-1.0,
    "extraversion": 0.0-1.0,
    "agreeableness": 0.0-1.0,
    "neuroticism": 0.0-1.0
  }},
  "communication_style": {{
    "formality": "formal|neutral|casual",
    "verbosity": "terse|moderate|verbose",
    "argument_style": "data-driven|anecdotal|authoritative|balanced",
    "tone": "aggressive|assertive|professional|diplomatic|passive"
  }},
  "beliefs": ["core professional belief 1 (Korean)", "core professional belief 2"],
  "likes": ["approach/method they favor (Korean)"],
  "dislikes": ["approach/method they oppose (Korean)"],
  "background": "Detailed professional background paragraph (Korean, 3-4 sentences)"
}}
"""

ENTITY_PERSONA_PROMPT = """당신은 시뮬레이션 토론의 참여자 프로필을 생성합니다.

아래 지식 그래프의 핵심 엔티티가 실제 토론에 참여한다고 가정하세요.
이 엔티티의 입장에서 전문성, 역할, 입장을 설정합니다.

토론 주제: {topic}

엔티티 정보:
- 이름: {entity_name}
- 유형: {entity_type}
- 설명: {entity_description}

연결된 관계:
{relations_context}

웹 검색으로 수집된 최신 정보:
{web_context}

이 엔티티가 토론에 참여한다면 어떤 입장/역할/전문성을 가질지 설정하세요.
예: "퀵커머스" 엔티티 → 퀵커머스 채널 전문가 / "인스타마트" → Swiggy Instamart 대표

JSON으로만 응답:
{{
  "name": "{entity_name} 전문가 (또는 적절한 역할명, 한국어)",
  "role": "English role title",
  "description": "전문적 배경 (한국어, 2-3문장)",
  "personality": "성격 특성 (한국어, 1-2문장)",
  "stance": "이 토론 주제에 대한 구체적 입장 (한국어, 2-3문장)",
  "goals": ["구체적 목표 1 (한국어)", "구체적 목표 2", "구체적 목표 3"],
  "knowledge": ["핵심 전문 지식 1", "핵심 전문 지식 2", "핵심 전문 지식 3"],
  "big_five": {{"openness": 0.0-1.0, "conscientiousness": 0.0-1.0, "extraversion": 0.0-1.0, "agreeableness": 0.0-1.0, "neuroticism": 0.0-1.0}},
  "communication_style": {{"formality": "formal|neutral|casual", "verbosity": "terse|moderate|verbose", "argument_style": "data-driven|anecdotal|authoritative|balanced", "tone": "aggressive|assertive|professional|diplomatic|passive"}},
  "beliefs": ["핵심 신념 1 (한국어)", "핵심 신념 2"],
  "likes": ["선호하는 접근법 (한국어)"],
  "dislikes": ["반대하는 접근법 (한국어)"],
  "background": "상세 배경 (한국어, 3-4문장)"
}}
"""

CONSISTENCY_CHECK_PROMPT = """다음 {count}명의 조직 이해관계자를 검토하세요.

안건: {topic}

이해관계자:
{personas_json}

검토 기준:
1. 각 역할이 서로 상충하는 뚜렷한 이해관계를 가지고 있는가?
2. stance가 안건에 구체적인가? (일반적 부서 설명이 아닌 이 안건에 대한 입장)
3. goals가 현실적인 부서 KPI와 긴장 관계를 반영하는가?
4. big_five 성격이 다양한가? (모두 비슷하면 안 됨)
5. communication_style이 다양한가?

각 이해관계자 간 핵심 관계도 설정하세요:
- 어떤 역할 쌍이 가장 큰 갈등을 가지는가?
- 어떤 역할 쌍이 자연스러운 동맹인가?

조정이 필요하면 stance, goals, big_five, communication_style을 날카롭게 수정하세요.
그리고 각 역할에 relationships 필드를 추가하세요.

JSON 배열로 응답:
[
  {{
    "name": "...",
    "stance": "...",
    "goals": ["..."],
    "personality": "...",
    "big_five": {{"openness": ..., "conscientiousness": ..., "extraversion": ..., "agreeableness": ..., "neuroticism": ...}},
    "communication_style": {{"formality": "...", "verbosity": "...", "argument_style": "...", "tone": "..."}},
    "relationships": {{
      "역할명1": "관계 설명 (예: 원가 문제로 자주 충돌)",
      "역할명2": "관계 설명 (예: 품질 기준에서 협력)"
    }}
  }},
  ...
]
"""


# ---------------------------------------------------------------------------
# PersonaFactory
# ---------------------------------------------------------------------------

class PersonaFactory:
    """Generates deep, topic-specific personas from knowledge graph."""

    def __init__(self, llm_client: BaseLLMClient):
        self.llm = llm_client
        self._personas: dict[str, PersonaProfile] = {}
        self._role_entity_map: dict[str, list[str]] = {}  # persona_id -> [entity_ids]

    async def generate_personas(
        self,
        ontology: OntologyResult,
        max_personas: int = 20,
        check_consistency: bool = True,
        disabled_roles: list[str] | None = None,
        custom_profiles: list[dict] | None = None,
    ) -> list[PersonaProfile]:
        """Generate topic-specific, deeply-specified personas.

        max_personas: 생성할 동적(LLM) 역할 개수. custom/entity는 호출자가
        이미 차감해서 넘겨야 한다. 여기서는 더 이상 빼지 않는다.
        custom_profiles: 프로파일링된 외부 인물 리스트 (persona_profiler 결과)
        """

        # max_personas is the number of DYNAMIC roles the caller wants.
        # custom_profiles are appended on top separately below.
        dynamic_slots = max(0, max_personas)

        # Phase 1: Generate dynamic roles from the topic (skip if 0)
        roles: list[dict] = []
        if dynamic_slots > 0:
            roles = await self._generate_stakeholder_roles(
                ontology.topic, ontology, dynamic_slots,
            )

        # Filter disabled roles
        if disabled_roles:
            roles = [r for r in roles if r["name"] not in disabled_roles]

        # Phase 2: Assign entities to roles by semantic relevance
        role_entities = self._assign_entities_to_roles(ontology, roles)

        log.info("persona_generation_start",
                 total_entities=len(ontology.entities),
                 roles=len(roles))

        # Phase 3: Generate deep persona profiles in parallel
        tasks = []
        for i, role in enumerate(roles):
            entities = role_entities.get(i, [])
            entity_relations = self._build_relation_context_for_entities(ontology, entities)
            tasks.append(self._generate_single(
                entities, ontology.topic, entity_relations, org_role=role,
            ))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        personas: list[PersonaProfile] = []
        seen_names: set[str] = set()
        for idx, persona in enumerate(results):
            if isinstance(persona, Exception) or persona is None:
                continue
            original_name = persona.name
            suffix = 2
            while persona.name in seen_names:
                persona.name = f"{original_name}_{suffix}"
                suffix += 1
            seen_names.add(persona.name)

            # Store entity mapping for relationship building
            entity_ids = [e.id for e in role_entities.get(idx, [])]
            self._role_entity_map[persona.id] = entity_ids

            personas.append(persona)
            log.info("persona_generated", name=persona.name, role=persona.role)

        # Add custom profiled personas (CEO/external figures)
        if custom_profiles:
            for cp in custom_profiles:
                name = cp.get("name", "Unknown")
                if name in seen_names:
                    name = f"{name}_외부"
                seen_names.add(name)

                persona = PersonaProfile(
                    name=name,
                    role=cp.get("role", "External Advisor"),
                    description=cp.get("description", ""),
                    personality=cp.get("personality", ""),
                    stance=cp.get("stance", ""),
                    goals=cp.get("goals", []),
                    knowledge=cp.get("knowledge", []),
                )
                # Store extra profiling data in relationships as context
                if cp.get("decision_style"):
                    persona.relationships["__decision_style__"] = cp["decision_style"]
                if cp.get("speech_style"):
                    persona.relationships["__speech_style__"] = cp["speech_style"]
                if cp.get("core_values"):
                    persona.relationships["__core_values__"] = ", ".join(cp["core_values"])

                personas.append(persona)
                log.info("custom_persona_added", name=name, role=persona.role)

        # Phase 4: Consistency check + relationship generation
        if check_consistency and len(personas) >= 3:
            personas = await self._check_consistency(personas, ontology.topic)

        # Phase 5: Build relationships from shared entities
        self._build_inter_persona_relationships(personas, ontology)

        # Store
        for p in personas:
            self._personas[p.id] = p

        log.info("persona_generation_complete", count=len(personas))
        return personas

    # -- Phase 1: Dynamic role generation -----------------------------------

    async def _generate_stakeholder_roles(
        self, topic: str, ontology: OntologyResult, count: int,
    ) -> list[dict]:
        """Generate topic-specific stakeholder roles via LLM."""

        # Build entity context (top 15 by centrality)
        entity_relation_count: dict[str, int] = {}
        for r in ontology.relations:
            entity_relation_count[r.source_id] = entity_relation_count.get(r.source_id, 0) + 1
            entity_relation_count[r.target_id] = entity_relation_count.get(r.target_id, 0) + 1

        sorted_entities = sorted(
            ontology.entities,
            key=lambda e: entity_relation_count.get(e.id, 0),
            reverse=True,
        )

        entity_lines = []
        for e in sorted_entities[:15]:
            desc = f"- {e.name} ({e.type}): {e.description}" if e.description else f"- {e.name} ({e.type})"
            if e.attributes:
                desc += f" [{', '.join(f'{k}={v}' for k, v in list(e.attributes.items())[:3])}]"
            entity_lines.append(desc)

        relation_lines = []
        entity_name_map = {e.id: e.name for e in ontology.entities}
        for r in ontology.relations[:10]:
            src = entity_name_map.get(r.source_id, r.source_id)
            tgt = entity_name_map.get(r.target_id, r.target_id)
            relation_lines.append(f"- {src} --[{r.relation_type}]--> {tgt}: {r.description}")

        prompt = STAKEHOLDER_EXTRACTION_PROMPT.format(
            count=count,
            topic=topic or "General discussion",
            entity_context="\n".join(entity_lines) if entity_lines else "(없음)",
            relation_context="\n".join(relation_lines) if relation_lines else "(없음)",
        )

        try:
            response = await self.llm.complete([
                {"role": "system", "content": "조직 전략 회의를 위한 이해관계자 역할을 설계합니다. 각 역할은 서로 상충하는 이해관계를 가져야 합니다. JSON 배열로만 응답하세요."},
                {"role": "user", "content": prompt},
            ], temperature=0.5)

            roles = self._parse_json(response)
            if not isinstance(roles, list):
                raise ValueError("Expected JSON array")

            # Validate each role has required fields
            valid_roles = []
            required_keys = {"name", "role", "dept", "focus"}
            for r in roles:
                if isinstance(r, dict) and required_keys.issubset(r.keys()):
                    if "perspective" not in r:
                        r["perspective"] = r.get("focus", "")
                    valid_roles.append(r)

            if len(valid_roles) >= count // 2:
                log.info("dynamic_roles_generated", count=len(valid_roles))
                return valid_roles[:count]

            log.warning("dynamic_roles_insufficient", valid=len(valid_roles), required=count // 2)
        except Exception as e:
            log.warning("dynamic_role_generation_failed", error=str(e))

        # Fallback to hardcoded roles
        log.info("using_fallback_roles")
        return FALLBACK_ROLES[:count]

    # -- Phase 2: Semantic entity-to-role assignment -------------------------

    def _assign_entities_to_roles(
        self, ontology: OntologyResult, roles: list[dict],
    ) -> dict[int, list[Entity]]:
        """Assign ontology entities to roles by keyword relevance."""

        if not ontology.entities:
            return {}

        # Centrality fallback
        entity_relation_count: dict[str, int] = {}
        for r in ontology.relations:
            entity_relation_count[r.source_id] = entity_relation_count.get(r.source_id, 0) + 1
            entity_relation_count[r.target_id] = entity_relation_count.get(r.target_id, 0) + 1

        most_central = sorted(
            ontology.entities,
            key=lambda e: entity_relation_count.get(e.id, 0),
            reverse=True,
        )

        result: dict[int, list[Entity]] = {}

        for role_idx, role in enumerate(roles):
            # Build role keywords
            role_text = " ".join([
                role.get("dept", ""),
                role.get("focus", ""),
                role.get("perspective", ""),
                role.get("name", ""),
            ]).lower()
            role_keywords = set(self._tokenize(role_text))

            # Score each entity
            scored: list[tuple[float, Entity]] = []
            for entity in ontology.entities:
                entity_text = " ".join([
                    entity.name,
                    entity.type,
                    entity.description,
                    json.dumps(entity.attributes, ensure_ascii=False) if entity.attributes else "",
                ]).lower()
                entity_keywords = set(self._tokenize(entity_text))

                if not role_keywords:
                    score = 0.0
                else:
                    score = len(role_keywords & entity_keywords) / len(role_keywords)
                scored.append((score, entity))

            # Take top 3 by relevance (minimum threshold 0.05)
            scored.sort(key=lambda x: x[0], reverse=True)
            assigned = [e for s, e in scored[:3] if s >= 0.05]

            # Fallback: most central entity
            if not assigned and most_central:
                assigned = [most_central[0]]

            result[role_idx] = assigned

        return result

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Simple tokenizer for keyword matching (handles Korean and English)."""
        import re
        # Split on whitespace, commas, periods, parentheses, etc.
        tokens = re.split(r'[\s,.\(\)\[\]{}:;/\-_·]+', text)
        # Filter short tokens and common particles
        stop = {"의", "을", "를", "이", "가", "은", "는", "에", "와", "과", "로", "으로",
                "및", "등", "위", "한", "a", "an", "the", "and", "or", "of", "for", "in", "to"}
        return [t for t in tokens if len(t) >= 2 and t not in stop]

    # -- Phase 3: Deep persona generation -----------------------------------

    async def _generate_single(
        self,
        entity_group: list[Entity],
        topic: str,
        entity_relations: list[str],
        org_role: Optional[dict] = None,
    ) -> Optional[PersonaProfile]:
        """Generate a single deep persona from role + entity group."""
        role = org_role or {}
        role_name = role.get("name", "분석가")
        role_title = role.get("role", "Analyst")
        dept = role.get("dept", "General")
        focus = role.get("focus", "General analysis")
        perspective = role.get("perspective", "")

        # Build entity context block
        entity_lines = []
        entity_knowledge_facts = []
        for entity in entity_group:
            line = f"- {entity.name} ({entity.type}): {entity.description}"
            if entity.attributes:
                attrs = ", ".join(f"{k}: {v}" for k, v in list(entity.attributes.items())[:5])
                line += f"\n  속성: {attrs}"
            entity_lines.append(line)
            # Extract concrete facts for entity_knowledge
            if entity.description:
                entity_knowledge_facts.append(f"{entity.name}: {entity.description}")
            for k, v in list(entity.attributes.items())[:3]:
                entity_knowledge_facts.append(f"{entity.name}의 {k}: {v}")

        if entity_relations:
            entity_lines.append("\n관계:")
            entity_lines.extend(f"  {r}" for r in entity_relations[:5])

        entity_context = "\n".join(entity_lines) if entity_lines else "No specific entity context"

        prompt = PERSONA_GENERATION_PROMPT.format(
            topic=topic or "General discussion",
            role_name=role_name,
            role_title=role_title,
            dept=dept,
            focus=focus,
            perspective=perspective,
            entity_context=entity_context,
        )

        try:
            response = await self.llm.complete([
                {
                    "role": "system",
                    "content": (
                        "You create deep, realistic organizational stakeholder profiles for strategy discussions. "
                        "Each role must have clear departmental priorities, specific personality traits, "
                        "and potential conflicts with other departments. "
                        "Respond with valid JSON only. All Korean text fields must be in Korean."
                    ),
                },
                {"role": "user", "content": prompt},
            ], temperature=0.7)

            data = self._parse_json(response)

            # Parse Big Five
            bf_data = data.get("big_five", {})
            big_five = BigFiveTraits(
                openness=self._clamp(bf_data.get("openness", 0.5)),
                conscientiousness=self._clamp(bf_data.get("conscientiousness", 0.5)),
                extraversion=self._clamp(bf_data.get("extraversion", 0.5)),
                agreeableness=self._clamp(bf_data.get("agreeableness", 0.5)),
                neuroticism=self._clamp(bf_data.get("neuroticism", 0.5)),
            )

            # Parse Communication Style
            cs_data = data.get("communication_style", {})
            comm_style = CommunicationStyle(
                formality=cs_data.get("formality", "neutral"),
                verbosity=cs_data.get("verbosity", "moderate"),
                argument_style=cs_data.get("argument_style", "balanced"),
                tone=cs_data.get("tone", "professional"),
            )

            return PersonaProfile(
                name=data.get("name", role_name),
                role=data.get("role", f"{role_title}, {dept}"),
                description=data.get("description", ""),
                personality=data.get("personality", ""),
                stance=data.get("stance", perspective),
                goals=data.get("goals", []),
                knowledge=data.get("knowledge", []),
                big_five=big_five,
                communication_style=comm_style,
                beliefs=data.get("beliefs", []),
                likes=data.get("likes", []),
                dislikes=data.get("dislikes", []),
                background=data.get("background", ""),
                entity_knowledge=entity_knowledge_facts[:10],
            )

        except Exception as e:
            log.error("persona_generation_error", role=role_name, error=str(e))
            return PersonaProfile(
                name=role_name,
                role=f"{role_title}, {dept}",
                description=f"{dept} 관점에서 안건 검토",
                stance=perspective or "부서 입장에서 검토 필요",
                goals=["부서 목표 달성", "리스크 최소화"],
                knowledge=[focus],
                entity_knowledge=entity_knowledge_facts[:5],
            )

    # -- Phase 4: Consistency check + relationship generation ----------------

    async def _check_consistency(
        self, personas: list[PersonaProfile], topic: str,
    ) -> list[PersonaProfile]:
        """Check and adjust persona set for diversity, consistency, and relationships."""
        personas_data = [
            {
                "name": p.name,
                "role": p.role,
                "personality": p.personality,
                "stance": p.stance,
                "goals": p.goals,
                "big_five": p.big_five.model_dump(),
                "communication_style": p.communication_style.model_dump(),
            }
            for p in personas
        ]

        prompt = CONSISTENCY_CHECK_PROMPT.format(
            count=len(personas),
            topic=topic,
            personas_json=json.dumps(personas_data, ensure_ascii=False, indent=2),
        )

        try:
            response = await self.llm.complete([
                {
                    "role": "system",
                    "content": (
                        "시뮬레이션 페르소나의 다양성, 현실성, 갈등 구조를 검토합니다. "
                        "JSON 배열로만 응답하세요."
                    ),
                },
                {"role": "user", "content": prompt},
            ], temperature=0.3)

            adjusted = self._parse_json(response)
            if isinstance(adjusted, list) and len(adjusted) == len(personas):
                name_to_persona = {p.name: p for p in personas}

                for adj in adjusted:
                    adj_name = adj.get("name", "")
                    persona = name_to_persona.get(adj_name)
                    if not persona:
                        continue

                    # Update fields if provided
                    if "stance" in adj:
                        persona.stance = adj["stance"]
                    if "personality" in adj:
                        persona.personality = adj["personality"]
                    if "goals" in adj and isinstance(adj["goals"], list):
                        persona.goals = adj["goals"]
                    if "big_five" in adj and isinstance(adj["big_five"], dict):
                        bf = adj["big_five"]
                        persona.big_five = BigFiveTraits(
                            openness=self._clamp(bf.get("openness", persona.big_five.openness)),
                            conscientiousness=self._clamp(bf.get("conscientiousness", persona.big_five.conscientiousness)),
                            extraversion=self._clamp(bf.get("extraversion", persona.big_five.extraversion)),
                            agreeableness=self._clamp(bf.get("agreeableness", persona.big_five.agreeableness)),
                            neuroticism=self._clamp(bf.get("neuroticism", persona.big_five.neuroticism)),
                        )
                    if "communication_style" in adj and isinstance(adj["communication_style"], dict):
                        cs = adj["communication_style"]
                        persona.communication_style = CommunicationStyle(
                            formality=cs.get("formality", persona.communication_style.formality),
                            verbosity=cs.get("verbosity", persona.communication_style.verbosity),
                            argument_style=cs.get("argument_style", persona.communication_style.argument_style),
                            tone=cs.get("tone", persona.communication_style.tone),
                        )

                    # Build relationships from consistency check
                    if "relationships" in adj and isinstance(adj["relationships"], dict):
                        for target_name, rel_desc in adj["relationships"].items():
                            # Find target persona
                            target_persona = name_to_persona.get(target_name)
                            if target_persona:
                                persona.relationships[target_persona.id] = rel_desc

                log.info("consistency_check_applied")

        except Exception as e:
            log.warning("consistency_check_failed", error=str(e))

        return personas

    # -- Phase 5: Shared-entity relationship building -----------------------

    def _build_inter_persona_relationships(
        self, personas: list[PersonaProfile], ontology: OntologyResult,
    ):
        """Build relationships based on shared entity assignments."""
        # Only add entity-based relationships if consistency check didn't populate them
        for i, p1 in enumerate(personas):
            for j, p2 in enumerate(personas):
                if i >= j:
                    continue

                # Skip if relationship already set by consistency check
                if p2.id in p1.relationships:
                    continue

                # Find shared entities
                entities_1 = set(self._role_entity_map.get(p1.id, []))
                entities_2 = set(self._role_entity_map.get(p2.id, []))
                shared = entities_1 & entities_2

                if shared:
                    entity_names = []
                    for eid in shared:
                        for e in ontology.entities:
                            if e.id == eid:
                                entity_names.append(e.name)
                                break

                    if entity_names:
                        rel_desc = f"{', '.join(entity_names[:2])} 관련 이해관계 교차 - 협력 또는 갈등 가능"
                        p1.relationships[p2.id] = f"{p2.name}: {rel_desc}"
                        p2.relationships[p1.id] = f"{p1.name}: {rel_desc}"

    # -- Entity-based persona generation ------------------------------------

    async def generate_entity_personas(
        self,
        entity_ids: list[str],
        ontology: OntologyResult,
        topic: str,
    ) -> list[PersonaProfile]:
        """지식 그래프 핵심 엔티티를 기반으로 페르소나를 생성.

        각 엔티티에 대해 웹 검색으로 최신 정보를 보강하고
        LLM으로 해당 엔티티의 전문가/대표 페르소나를 생성합니다.
        """
        if not entity_ids:
            return []

        entity_map = {e.id: e for e in ontology.entities}
        name_map = {e.id: e.name for e in ontology.entities}
        selected = [entity_map[eid] for eid in entity_ids if eid in entity_map]

        if not selected:
            return []

        log.info("entity_persona_generation_start", count=len(selected))

        tasks = []
        for entity in selected:
            # 연결된 관계 수집
            relations = self._build_relation_context_for_entities(ontology, [entity])
            tasks.append(self._generate_entity_persona(entity, ontology, topic, relations))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        personas = []
        for result in results:
            if isinstance(result, Exception) or result is None:
                continue
            result.agent_tier = "entity"
            personas.append(result)
            self._personas[result.id] = result
            log.info("entity_persona_generated", name=result.name, entity=result.entity_knowledge[:1])

        return personas

    async def _generate_entity_persona(
        self,
        entity: Entity,
        ontology: OntologyResult,
        topic: str,
        relations: list[str],
    ) -> Optional[PersonaProfile]:
        """단일 엔티티에서 페르소나를 생성 (웹 검색 보강 포함)."""

        # 1. 웹 검색으로 최신 정보 수집
        web_snippets = []
        try:
            from core.auto_search import search_web
            # 엔티티 타입과 관련 키워드 조합
            keywords = [topic.split()[0] if topic else "", entity.type]
            keywords = [k for k in keywords if k]
            search_results = await search_web(
                entity.name,
                keywords=keywords[:3],
                max_results=5,
            )
            web_snippets = [
                f"- {r.get('title', '')}: {r.get('snippet', '')}"
                for r in search_results[:5]
                if r.get("snippet")
            ]
        except Exception as e:
            log.warning("entity_web_search_failed", entity=entity.name, error=str(e))

        web_context = "\n".join(web_snippets) if web_snippets else "(검색 결과 없음)"
        relations_context = "\n".join(f"  {r}" for r in relations[:8]) if relations else "(없음)"

        # 2. 엔티티 기반 지식 수집
        entity_knowledge_facts = []
        if entity.description:
            entity_knowledge_facts.append(f"{entity.name}: {entity.description}")
        for k, v in list(entity.attributes.items())[:5]:
            entity_knowledge_facts.append(f"{entity.name}의 {k}: {v}")
        # 웹 검색 결과도 knowledge에 추가
        for snippet in web_snippets[:3]:
            entity_knowledge_facts.append(snippet.lstrip("- "))

        # 3. LLM으로 페르소나 생성
        prompt = ENTITY_PERSONA_PROMPT.format(
            topic=topic or "General discussion",
            entity_name=entity.name,
            entity_type=entity.type,
            entity_description=entity.description or "(설명 없음)",
            relations_context=relations_context,
            web_context=web_context,
        )

        try:
            response = await self.llm.complete([
                {
                    "role": "system",
                    "content": (
                        "지식 그래프의 핵심 엔티티를 토론 참여자로 변환합니다. "
                        "엔티티의 특성과 관계를 기반으로 현실적인 전문가 페르소나를 만드세요. "
                        "JSON으로만 응답하세요. 한국어 필드는 한국어로."
                    ),
                },
                {"role": "user", "content": prompt},
            ], temperature=0.6)

            data = self._parse_json(response)

            bf_data = data.get("big_five", {})
            big_five = BigFiveTraits(
                openness=self._clamp(bf_data.get("openness", 0.6)),
                conscientiousness=self._clamp(bf_data.get("conscientiousness", 0.7)),
                extraversion=self._clamp(bf_data.get("extraversion", 0.5)),
                agreeableness=self._clamp(bf_data.get("agreeableness", 0.5)),
                neuroticism=self._clamp(bf_data.get("neuroticism", 0.3)),
            )

            cs_data = data.get("communication_style", {})
            comm_style = CommunicationStyle(
                formality=cs_data.get("formality", "professional"),
                verbosity=cs_data.get("verbosity", "moderate"),
                argument_style=cs_data.get("argument_style", "data-driven"),
                tone=cs_data.get("tone", "assertive"),
            )

            return PersonaProfile(
                name=data.get("name", f"{entity.name} 전문가"),
                role=data.get("role", f"{entity.type} Expert"),
                description=data.get("description", ""),
                personality=data.get("personality", ""),
                stance=data.get("stance", ""),
                goals=data.get("goals", []),
                knowledge=data.get("knowledge", []),
                big_five=big_five,
                communication_style=comm_style,
                beliefs=data.get("beliefs", []),
                likes=data.get("likes", []),
                dislikes=data.get("dislikes", []),
                background=data.get("background", ""),
                entity_knowledge=entity_knowledge_facts[:15],
                agent_tier="entity",
            )

        except Exception as e:
            log.error("entity_persona_error", entity=entity.name, error=str(e))
            return PersonaProfile(
                name=f"{entity.name} 전문가",
                role=f"{entity.type} Expert",
                description=f"{entity.name} 관점에서 토론 참여",
                stance=f"{entity.name}의 이해관계를 대변",
                goals=[f"{entity.name} 관련 전략 수립"],
                knowledge=[entity.description or entity.name],
                entity_knowledge=entity_knowledge_facts[:5],
                agent_tier="entity",
            )

    @staticmethod
    def select_top_entities(
        ontology: OntologyResult,
        max_count: int = 5,
    ) -> list[dict]:
        """degree centrality 기준 상위 엔티티 목록 반환 (UI 추천용)."""
        degree: dict[str, int] = {}
        for r in ontology.relations:
            degree[r.source_id] = degree.get(r.source_id, 0) + 1
            degree[r.target_id] = degree.get(r.target_id, 0) + 1

        sorted_entities = sorted(
            ontology.entities,
            key=lambda e: degree.get(e.id, 0),
            reverse=True,
        )

        return [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "description": e.description,
                "degree": degree.get(e.id, 0),
            }
            for e in sorted_entities[:max_count]
        ]

    # -- Utility helpers ---------------------------------------------------

    def _build_relation_context_for_entities(
        self, ontology: OntologyResult, entities: list[Entity],
    ) -> list[str]:
        """Build relation descriptions for a group of entities."""
        entity_map = {e.id: e.name for e in ontology.entities}
        entity_ids = {e.id for e in entities}
        result = []

        for rel in ontology.relations:
            if rel.source_id in entity_ids:
                target_name = entity_map.get(rel.target_id, "Unknown")
                result.append(f"{entity_map.get(rel.source_id, '?')} --[{rel.relation_type}]--> {target_name}: {rel.description}")
            elif rel.target_id in entity_ids:
                source_name = entity_map.get(rel.source_id, "Unknown")
                result.append(f"{source_name} --[{rel.relation_type}]--> {entity_map.get(rel.target_id, '?')}: {rel.description}")

        return result

    @staticmethod
    def _clamp(value, lo=0.0, hi=1.0) -> float:
        """Clamp a value to [lo, hi]."""
        try:
            return max(lo, min(hi, float(value)))
        except (TypeError, ValueError):
            return 0.5

    def _parse_json(self, text: str) -> dict | list:
        """Parse JSON from LLM response, handling markdown code fences."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)

    def get_personas(self) -> list[PersonaProfile]:
        return list(self._personas.values())

    def get_persona(self, persona_id: str) -> Optional[PersonaProfile]:
        return self._personas.get(persona_id)
