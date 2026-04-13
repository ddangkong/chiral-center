"""Hybrid NER + LLM ontology extraction pipeline.

First pass: KoELECTRA NER for high-precision entity extraction.
Second pass: LLM for relations, abstract concepts, and low-confidence verification.
"""
from __future__ import annotations

import json
import uuid
import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable

from core.koner_extractor import KoNERExtractor, NEREntity, koner
from llm.base import BaseLLMClient
from models.document import TextChunk
from models.ontology import (
    Entity,
    EntityType,
    OntologyResult,
    OntologySchema,
    Relation,
    RelationType,
)
from utils.chunker import TextChunker
from utils.logger import log

CONFIDENCE_THRESHOLD = 0.85

HYBRID_EXTRACTION_PROMPT = """Extract entities and relations from this text chunk.

Topic: {topic}
Purpose: {purpose}

Already confirmed entities (high confidence, do NOT re-extract these):
{confirmed_entities}

Focus on:
1. Relations between the confirmed entities and any new entities you find.
2. Entities the NER may have missed: trends, strategies, abstract concepts, events, policies.
3. Verify these uncertain entities (confirm or reject each):
{uncertain_entities}

Only keep entities that are central enough to form important relations in the final graph.
Prefer canonical names and merge aliases or alternate surface forms into one entity.
Do not include weak, generic, or one-off concepts unless they are clearly central.

Allowed entity types: {entity_types}
Allowed relation types: {relation_types}

Text chunk:
{chunk}

Return JSON only:
{{
  "entities": [
    {{
      "name": "entity name",
      "type": "entity type",
      "description": "brief grounded description",
      "attributes": {{}},
      "evidence": "short supporting quote"
    }}
  ],
  "relations": [
    {{
      "source": "entity name",
      "target": "entity name",
      "relation_type": "RELATION_TYPE",
      "weight": 0.8,
      "description": "grounded relationship description",
      "evidence": "short supporting quote"
    }}
  ],
  "verified_uncertain": [
    {{
      "name": "entity name",
      "valid": true,
      "corrected_name": "optional corrected name"
    }}
  ]
}}
"""

HYBRID_SCHEMA_PROMPT = """Based on these NER-detected entity types and the document text, propose a complete ontology schema.

Topic: {topic}
Purpose: {purpose}

NER-detected types: {ner_types}

Sample text:
{sample_text}

Return JSON only with entity types and relation types. Include the NER-detected types plus any additional types needed (Trend, Strategy, Event, Policy, etc.):
{{
  "entity_types": [
    {{
      "name": "Person",
      "description": "Human actors",
      "attributes": ["role", "affiliation"]
    }}
  ],
  "relation_types": [
    {{
      "name": "INFLUENCES",
      "description": "Source influences target",
      "source_type": "Person",
      "target_type": "Organization"
    }}
  ]
}}
"""


class HybridExtractor:
    """Hybrid NER + LLM extraction pipeline.

    Uses KoELECTRA for fast, high-precision entity extraction, then
    selectively invokes the LLM only for chunks needing relation extraction
    or entity verification.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        chunk_size: int = 2800,
        overlap: int = 280,
        ner_extractor: KoNERExtractor | None = None,
    ):
        self.llm = llm_client
        self.chunker = TextChunker(chunk_size=chunk_size, overlap=overlap)
        self.ner = ner_extractor or koner
        self._results: dict[str, OntologyResult] = {}

    async def _report_progress(
        self,
        callback: Callable[[int, str], Awaitable[None] | None] | None,
        progress: int,
        message: str,
    ) -> None:
        if not callback:
            return
        result = callback(progress, message)
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _normalize_entity_key(name: str) -> str:
        normalized = name.lower().strip()
        for ch in ['"', "'", "`", "(", ")", "[", "]", "{", "}", ",", ".", ":", ";", "/", "\\"]:
            normalized = normalized.replace(ch, " ")
        return " ".join(normalized.split())

    @classmethod
    def _is_low_signal_entity(cls, name: str, description: str = "") -> bool:
        normalized = cls._normalize_entity_key(name)
        if len(normalized) < 2:
            return True
        low_signal = {
            "issue", "problem", "system", "company", "person", "people", "organization",
            "policy", "technology", "event", "document", "text", "article", "report",
            "market", "industry", "trend", "strategy", "plan", "project", "service",
        }
        if normalized in low_signal:
            return True
        if normalized.startswith("this ") or normalized.startswith("these "):
            return True
        if description and len(description.strip()) < 8 and "generic" in description.lower():
            return True
        return False

    async def extract(
        self,
        text: str,
        topic: str = "",
        purpose: str = "",
        progress_callback: Callable[[int, str], Awaitable[None] | None] | None = None,
    ) -> OntologyResult:
        """Main entry point - hybrid NER+LLM extraction."""
        result_id = str(uuid.uuid4())
        topic = topic or "General analysis"
        purpose = purpose or "Build a grounded ontology for simulation"

        # 1. Chunk the text
        chunks = self.chunker.split(text)
        log.info(
            "hybrid_start",
            topic=topic,
            chunks=len(chunks),
            text_len=len(text),
        )
        await self._report_progress(progress_callback, 8, "문서를 나누고 하이브리드 추출을 준비하는 중...")

        # 2. Run KoNER on all chunks
        chunk_texts = [c.text for c in chunks]
        ner_entities = self.ner.extract_from_chunks(chunk_texts)
        log.info("hybrid_ner_done", ner_count=len(ner_entities))
        await self._report_progress(progress_callback, 24, "KoNER로 핵심 엔티티 후보를 찾는 중...")

        # 3. Run rule-based extraction and merge
        rule_entities: list[NEREntity] = []
        for chunk_text in chunk_texts:
            rule_entities.extend(self.ner.extract_with_rules(chunk_text))
        all_ner = self._merge_ner_results(ner_entities, rule_entities)
        log.info("hybrid_ner_merged", total=len(all_ner))
        await self._report_progress(progress_callback, 38, "NER 결과를 병합하고 정제하는 중...")

        # 4. Split by confidence
        high_conf = [e for e in all_ner if e.confidence >= CONFIDENCE_THRESHOLD]
        low_conf = [e for e in all_ner if e.confidence < CONFIDENCE_THRESHOLD]
        log.info(
            "hybrid_confidence_split",
            high=len(high_conf),
            low=len(low_conf),
        )
        await self._report_progress(progress_callback, 48, "신뢰도 기준으로 엔티티 후보를 분류하는 중...")

        # 5. NER 결과 요약 + 샘플 3개 → LLM 1회로 스키마+관계+검증 통합 추출
        schema, llm_entities, relations, verified = await self._llm_single_pass(
            chunks, high_conf, low_conf, topic, purpose,
        )
        log.info(
            "hybrid_llm_done",
            llm_calls=1,
            schema_types=len(schema.entity_types),
            llm_entities=len(llm_entities),
            relations=len(relations),
            verified=len(verified),
        )
        await self._report_progress(progress_callback, 72, "LLM으로 관계와 누락 엔티티를 검토하는 중...")

        # 8. Merge all entities into final Entity list
        final_entities = self._build_final_entities(
            high_conf, low_conf, llm_entities, verified,
        )
        log.info("hybrid_entities_final", count=len(final_entities))
        await self._report_progress(progress_callback, 84, "엔티티를 통합하고 중복을 제거하는 중...")

        # 9. Resolve relation entity references
        filtered_relations = self._filter_relations_against_entities(relations, final_entities)
        final_relations = self._resolve_relations(filtered_relations, final_entities)
        log.info("hybrid_relations_final", count=len(final_relations))
        await self._report_progress(progress_callback, 94, "관계를 엔티티에 연결하고 최종 그래프를 정리하는 중...")

        if final_relations:
            related_ids = {r.source_id for r in final_relations} | {r.target_id for r in final_relations}
            final_entities = [entity for entity in final_entities if entity.id in related_ids]

        result = OntologyResult(
            id=result_id,
            schema_def=schema,
            entities=final_entities,
            relations=final_relations,
            topic=topic,
            purpose=purpose,
        )
        self._results[result_id] = result
        return result

    def get_result(self, result_id: str) -> OntologyResult | None:
        return self._results.get(result_id)

    def _filter_relations_against_entities(
        self,
        raw_relations: list[dict],
        entities: list[Entity],
    ) -> list[dict]:
        entity_keys = {self._normalize_entity_key(entity.name) for entity in entities}
        filtered: list[dict] = []
        for relation in raw_relations:
            src = self._normalize_entity_key(str(relation.get("source", "")))
            tgt = self._normalize_entity_key(str(relation.get("target", "")))
            src_ok = any(src == key or src in key or key in src for key in entity_keys)
            tgt_ok = any(tgt == key or tgt in key or key in tgt for key in entity_keys)
            if src_ok and tgt_ok:
                filtered.append(relation)
        return filtered

    # -- NER merging --------------------------------------------------------

    def _merge_ner_results(
        self,
        ner_entities: list[NEREntity],
        rule_entities: list[NEREntity],
    ) -> list[NEREntity]:
        """Merge NER and rule-based entities, dedup by name+type."""
        best: dict[tuple[str, str], NEREntity] = {}
        for e in ner_entities:
            key = (e.name.lower().strip(), e.type)
            if key not in best or e.confidence > best[key].confidence:
                best[key] = e
        # Rule-based entities only added if not already present with higher conf
        for e in rule_entities:
            key = (e.name.lower().strip(), e.type)
            if key not in best or e.confidence > best[key].confidence:
                best[key] = e
        return sorted(best.values(), key=lambda x: x.confidence, reverse=True)

    # -- Schema extraction --------------------------------------------------

    async def _extract_schema(
        self,
        chunks: list[TextChunk],
        ner_entities: list[NEREntity],
        topic: str,
        purpose: str,
    ) -> OntologySchema:
        """Derive schema from NER types + LLM augmentation."""
        # Collect unique NER types
        ner_types = sorted({e.type for e in ner_entities})

        # Sample text for LLM schema proposal
        step = max(1, len(chunks) // 4)
        sampled = chunks[::step][:4]
        sample_text = "\n---\n".join(c.text[:800] for c in sampled)

        try:
            response = await self.llm.complete(
                [
                    {
                        "role": "system",
                        "content": "You design ontologies. Respond with valid JSON only.",
                    },
                    {
                        "role": "user",
                        "content": HYBRID_SCHEMA_PROMPT.format(
                            topic=topic,
                            purpose=purpose,
                            ner_types=", ".join(ner_types) if ner_types else "None detected",
                            sample_text=sample_text[:3200],
                        ),
                    },
                ],
                temperature=0.2,
                max_tokens=2000,
            )
            data = self._parse_json(response)
            schema = OntologySchema(
                entity_types=[
                    EntityType(**item) for item in data.get("entity_types", [])
                ],
                relation_types=[
                    RelationType(**item) for item in data.get("relation_types", [])
                ],
            )
        except Exception as exc:
            log.warning("hybrid_schema_failed", error=str(exc)[:120])
            # Fallback: build schema from NER types only
            schema = OntologySchema(
                entity_types=[
                    EntityType(name=t, description=f"NER-detected {t}")
                    for t in ner_types
                ] if ner_types else [EntityType(name="Entity", description="General entity")],
                relation_types=[
                    RelationType(name="RELATED_TO", description="General relation"),
                ],
            )

        # Ensure all NER types are in the schema
        existing_type_names = {et.name for et in schema.entity_types}
        for t in ner_types:
            if t not in existing_type_names:
                schema.entity_types.append(
                    EntityType(name=t, description=f"NER-detected {t}")
                )

        return schema

    # -- Chunk selection for LLM -------------------------------------------

    def _select_chunks_for_llm(
        self,
        chunks: list[TextChunk],
        ner_entities: list[NEREntity],
    ) -> list[TextChunk]:
        """Select chunks that need LLM processing.

        A chunk needs LLM if:
        - It contains low-confidence entities, OR
        - It contains no NER entities at all (may have abstract concepts)
        """
        # Map entities to chunks by checking if entity source_text appears in chunk
        chunks_with_low_conf: set[int] = set()
        chunks_with_any_entity: set[int] = set()

        for entity in ner_entities:
            for chunk in chunks:
                if entity.name in chunk.text:
                    chunks_with_any_entity.add(chunk.index)
                    if entity.confidence < CONFIDENCE_THRESHOLD:
                        chunks_with_low_conf.add(chunk.index)

        selected: list[TextChunk] = []
        for chunk in chunks:
            if chunk.index in chunks_with_low_conf or chunk.index not in chunks_with_any_entity:
                selected.append(chunk)

        # If no chunks selected (all high conf), still process a sample for relations
        if not selected and chunks:
            step = max(1, len(chunks) // 4)
            selected = chunks[::step][:4]

        return selected

    # -- Single-pass LLM extraction (1 call) ---------------------------------

    async def _llm_single_pass(
        self,
        chunks: list[TextChunk],
        high_conf: list[NEREntity],
        low_conf: list[NEREntity],
        topic: str,
        purpose: str,
    ) -> tuple[OntologySchema, list[dict], list[dict], list[dict]]:
        """NER 요약 + 샘플 텍스트 3개 → LLM 1회로 스키마+관계+엔티티+검증 통합 추출."""

        # NER 엔티티 전체 이름 목록 (정확한 이름 제공)
        all_entity_names = sorted({e.name for e in high_conf})
        entity_list = "\n".join(f"  - {name}" for name in all_entity_names[:100])

        # 대표 샘플 3개 선택 (균등 분포)
        n = len(chunks)
        indices = [0, n // 2, n - 1] if n >= 3 else list(range(n))
        samples = "\n\n---\n\n".join(chunks[i].text[:1200] for i in indices if i < n)

        prompt = f"""주제: {topic}
목적: {purpose}

아래 엔티티 목록과 원문을 분석하여 엔티티 간의 관계를 추출하세요.

=== 엔티티 목록 (source/target에 이 이름을 정확히 그대로 사용할 것) ===
{entity_list}

=== 원문 샘플 ===
{samples}

규칙:
- source와 target에는 반드시 위 목록의 이름을 **그대로** 사용 (오타, 변형 불가)
- 원문에 근거가 있는 관계만 포함
- 근거 없이 억지로 엮지 마세요

JSON 형식:
{{
  "relation_types": [
    {{"name": "COMPETES_WITH", "description": "경쟁 관계"}},
    {{"name": "OPERATES_IN", "description": "시장/지역에서 활동"}},
    {{"name": "PRODUCES", "description": "제품 생산"}}
  ],
  "relations": [
    {{"source": "정확한 엔티티 이름", "target": "정확한 엔티티 이름", "relation_type": "COMPETES_WITH", "weight": 0.9, "description": "근거 설명"}}
  ]
}}"""

        try:
            response = await self.llm.complete(
                [
                    {"role": "system", "content": "당신은 지식 그래프 전문가입니다. 원문에 근거가 있는 엔티티 간 관계만 추출하세요. 근거 없는 관계는 포함하지 마세요. JSON만 응답하세요."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=3000,
            )
            data = self._parse_json(response)
            log.info("hybrid_llm_raw",
                      relation_types=len(data.get("relation_types", [])),
                      relations=len(data.get("relations", [])),
                      new_entities=len(data.get("new_entities", [])),
                      response_len=len(response))
        except Exception as exc:
            log.error("hybrid_single_pass_failed", error=str(exc)[:200])
            # NER 결과만으로 기본 스키마 생성
            ner_types = sorted({e.type for e in high_conf})
            schema = OntologySchema(
                entity_types=[EntityType(name=t, description=f"NER-detected {t}") for t in ner_types],
                relation_types=[RelationType(name="RELATED_TO", description="General relation")],
            )
            return schema, [], [], []

        # 스키마: NER 타입에서 자동 생성 + LLM 관계 타입 추가
        schema = OntologySchema()
        ner_types = sorted({e.type for e in high_conf})
        for t in ner_types:
            schema.entity_types.append(EntityType(name=t, description=f"NER-detected {t}"))

        for rt in data.get("relation_types", []):
            try:
                schema.relation_types.append(RelationType(**rt))
            except Exception:
                schema.relation_types.append(RelationType(name=rt.get("name", "RELATED_TO"), description=rt.get("description", "")))

        if not schema.relation_types:
            schema.relation_types.append(RelationType(name="RELATED_TO", description="General relation"))

        log.info("hybrid_relations_from_llm", count=len(data.get("relations", [])))

        return (
            schema,
            data.get("new_entities", []),
            data.get("relations", []),
            data.get("verified_uncertain", []),
        )

    # -- Legacy: per-chunk LLM extraction (kept for compatibility) -----------

    async def _llm_extract(
        self,
        chunks: list[TextChunk],
        high_conf: list[NEREntity],
        low_conf: list[NEREntity],
        schema: OntologySchema,
        topic: str,
        purpose: str,
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Run LLM extraction on selected chunks.

        Returns (new_entities, relations, verified_uncertain).
        """
        entity_types = ", ".join(et.name for et in schema.entity_types) or "Entity"
        relation_types = ", ".join(rt.name for rt in schema.relation_types) or "RELATED_TO"

        confirmed_str = "\n".join(
            f"- {e.name} ({e.type}, confidence={e.confidence:.2f})"
            for e in high_conf[:50]  # cap to avoid prompt overflow
        ) or "None"

        uncertain_str = "\n".join(
            f"- {e.name} ({e.type}, confidence={e.confidence:.2f})"
            for e in low_conf[:30]
        ) or "None"

        all_entities: list[dict] = []
        all_relations: list[dict] = []
        all_verified: list[dict] = []

        import asyncio
        sem = asyncio.Semaphore(5)  # 최대 5개 병렬

        async def _process_chunk(chunk: TextChunk):
            async with sem:
                try:
                    response = await self.llm.complete(
                        [
                            {
                                "role": "system",
                                "content": (
                                    "Extract entities and relations. "
                                    "Respond with valid JSON only."
                                ),
                            },
                            {
                                "role": "user",
                                "content": HYBRID_EXTRACTION_PROMPT.format(
                                    topic=topic,
                                    purpose=purpose,
                                    confirmed_entities=confirmed_str,
                                    uncertain_entities=uncertain_str,
                                    entity_types=entity_types,
                                    relation_types=relation_types,
                                    chunk=chunk.text[:3500],
                                ),
                            },
                        ],
                        temperature=0.2,
                        max_tokens=3000,
                    )
                    data = self._parse_json(response)
                    entities = data.get("entities", [])
                    for e in entities:
                        e["_chunk_index"] = chunk.index
                    relations = data.get("relations", [])
                    for r in relations:
                        r["_chunk_index"] = chunk.index
                    return entities, relations, data.get("verified_uncertain", [])
                except Exception as exc:
                    log.warning(
                        "hybrid_llm_chunk_failed",
                        chunk=chunk.index,
                        error=str(exc)[:120],
                    )
                    return [], [], []

        log.info("hybrid_llm_parallel_start", chunks=len(chunks), concurrency=5)
        results = await asyncio.gather(*[_process_chunk(c) for c in chunks])
        for entities, relations, verified in results:
            all_entities.extend(entities)
            all_relations.extend(relations)
            all_verified.extend(verified)

        return all_entities, all_relations, all_verified

    # -- Final entity assembly ---------------------------------------------

    def _build_final_entities(
        self,
        high_conf: list[NEREntity],
        low_conf: list[NEREntity],
        llm_entities: list[dict],
        verified: list[dict],
    ) -> list[Entity]:
        """Merge NER entities and LLM entities into final Entity list."""
        seen: dict[str, Entity] = {}

        # 1. All high-confidence NER entities go in directly
        for ner_e in high_conf:
            key = self._normalize_entity_key(ner_e.name)
            if key not in seen and not self._is_low_signal_entity(ner_e.name):
                seen[key] = Entity(
                    name=ner_e.name,
                    type=ner_e.type,
                    description=f"NER-extracted ({ner_e.ner_tag})",
                    attributes={
                        "confidence": ner_e.confidence,
                        "source": "ner",
                        "evidence": ner_e.source_text,
                    },
                )

        # 2. Process verification results for low-conf entities
        verified_map: dict[str, dict] = {}
        for v in verified:
            name = self._normalize_entity_key(str(v.get("name", "")))
            if name:
                verified_map[name] = v

        for ner_e in low_conf:
            key = self._normalize_entity_key(ner_e.name)
            if key in seen:
                continue
            v_info = verified_map.get(key)
            if v_info and v_info.get("valid", False):
                corrected = v_info.get("corrected_name", "").strip()
                final_name = corrected if corrected else ner_e.name
                final_key = self._normalize_entity_key(final_name)
                if final_key not in seen and not self._is_low_signal_entity(final_name):
                    seen[final_key] = Entity(
                        name=final_name,
                        type=ner_e.type,
                        description=f"NER-extracted, LLM-verified ({ner_e.ner_tag})",
                        attributes={
                            "confidence": ner_e.confidence,
                            "source": "ner+llm_verified",
                            "evidence": ner_e.source_text,
                        },
                    )
            elif v_info is None:
                # Not verified by LLM -- still include if conf is reasonable
                if ner_e.confidence >= 0.72 and not self._is_low_signal_entity(ner_e.name):
                    seen[key] = Entity(
                        name=ner_e.name,
                        type=ner_e.type,
                        description=f"NER-extracted, unverified ({ner_e.ner_tag})",
                        attributes={
                            "confidence": ner_e.confidence,
                            "source": "ner_unverified",
                            "evidence": ner_e.source_text,
                        },
                    )
            # If v_info.valid is False, entity is rejected -- skip

        # 3. Add LLM-discovered entities (not already from NER)
        for llm_e in llm_entities:
            name = str(llm_e.get("name", "")).strip()
            if not name:
                continue
            key = self._normalize_entity_key(name)
            if self._is_low_signal_entity(name, llm_e.get("description", "")):
                continue
            if key in seen:
                # Enrich existing entity description if LLM provides more detail
                existing = seen[key]
                llm_desc = llm_e.get("description", "")
                if llm_desc and len(llm_desc) > len(existing.description):
                    existing.description = llm_desc
                continue
            seen[key] = Entity(
                name=name,
                type=llm_e.get("type", "Entity"),
                description=llm_e.get("description", ""),
                attributes={
                    "source": "llm",
                    **(llm_e.get("attributes", {})),
                },
            )

        return list(seen.values())

    # -- Relation resolution -----------------------------------------------

    def _resolve_relations(
        self,
        raw_relations: list[dict],
        entities: list[Entity],
    ) -> list[Relation]:
        """Map relation source/target names to entity IDs and deduplicate.
        Uses fuzzy matching: exact → contains → partial."""
        # Build name -> entity lookup (exact)
        name_map: dict[str, Entity] = {}
        for entity in entities:
            name_map[self._normalize_entity_key(entity.name)] = entity

        def _find_entity(name: str) -> Entity | None:
            key = self._normalize_entity_key(name)
            # 1. exact match
            if key in name_map:
                return name_map[key]
            # 2. entity name contains search name, or vice versa
            for ename, entity in name_map.items():
                if key in ename or ename in key:
                    return entity
            return None

        deduped: list[Relation] = []
        seen: set[tuple[str, str, str]] = set()
        matched = 0
        skipped = 0

        for r in raw_relations:
            src_name = str(r.get("source", ""))
            tgt_name = str(r.get("target", ""))
            rel_type = str(r.get("relation_type", "RELATED_TO")).upper()

            src = _find_entity(src_name)
            tgt = _find_entity(tgt_name)

            if not src or not tgt:
                skipped += 1
                continue
                # 매칭 실패 시 새 엔티티 생성
                if not src:
                    src = Entity(name=src_name, entity_type="Concept", description="LLM 관계에서 참조")
                    entities.append(src)
                    name_map[src_name.lower().strip()] = src
                if not tgt:
                    tgt = Entity(name=tgt_name, entity_type="Concept", description="LLM 관계에서 참조")
                    entities.append(tgt)
                    name_map[tgt_name.lower().strip()] = tgt

            key = (src.id, tgt.id, rel_type)
            if key in seen:
                continue
            seen.add(key)
            matched += 1

            deduped.append(Relation(
                source_id=src.id,
                target_id=tgt.id,
                relation_type=rel_type,
                weight=float(r.get("weight", 0.5)),
                description=r.get("description", ""),
            ))

        log.info("resolve_relations", raw=len(raw_relations), matched=matched, skipped=skipped)
        return deduped

    # -- Helpers -----------------------------------------------------------

    def _parse_json(self, text: str) -> dict | list:
        """Parse JSON from LLM response, stripping markdown fences."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)
