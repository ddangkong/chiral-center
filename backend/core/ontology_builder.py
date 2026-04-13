"""LLM-based ontology extraction from documents."""
import json
import uuid
import asyncio
import inspect
from collections.abc import Awaitable, Callable

from llm.base import BaseLLMClient
from models.ontology import (
    EntityType, RelationType, Entity, Relation,
    OntologySchema, OntologyResult,
)
from utils.logger import log


SCHEMA_EXTRACTION_PROMPT = """You are an expert ontologist. Analyze the following document text and extract an ontology schema.

The simulation topic is: {topic}
The analysis purpose is: {purpose}

Identify:
1. Entity types for only the core actors, organizations, events, technologies, policies, and concepts that are central to the document's main story.
2. Relation types that capture the strongest, simulation-relevant relationships between those core entities.

For each entity type, list key attributes.
For each relation type, specify source and target entity types.

Do not create overly fine-grained or redundant entity types.
Prefer a compact schema with broad but meaningful categories.

Respond in JSON format ONLY:
{{
  "entity_types": [
    {{"name": "Person", "description": "Individual actors", "attributes": ["role", "stance", "influence_level"]}}
  ],
  "relation_types": [
    {{"name": "WORKS_FOR", "description": "Employment", "source_type": "Person", "target_type": "Organization"}}
  ]
}}

Full document text:
{text}
"""

ENTITY_EXTRACTION_PROMPT = """You are an expert at extracting structured entities from text.

Topic: {topic}
Purpose: {purpose}

Entity types to extract: {entity_types}

Extract only the entities that are important enough to participate in the document's main relationships, arguments, or events.
Do not include throwaway mentions, generic nouns, one-off background details, or entities that do not affect the graph structure.
Prefer canonical names. Merge aliases and surface forms into one representative entity.

For each entity provide:
- name: the entity name
- type: one of the defined entity types
- attributes: relevant attributes as key-value pairs
- description: brief description

Respond in JSON array format ONLY:
[
  {{"name": "홍길동", "type": "Person", "attributes": {{"role": "CEO", "stance": "기술 낙관론"}}, "description": "AI 스타트업 대표"}}
]

Text:
{text}
"""

RELATION_EXTRACTION_PROMPT = """You are an expert at extracting relationships between entities.

Topic: {topic}
Purpose: {purpose}

Known entities:
{entities}

Relation types: {relation_types}

Extract only grounded, meaningful relationships from the text. Prefer fewer, stronger relations over exhaustive weak links.
If two entities are only loosely associated or merely co-mentioned, do not create a relationship.

For each relationship:
- source: source entity name
- target: target entity name
- relation_type: one of the defined relation types
- weight: importance 0.0-1.0
- description: brief description of the relationship

Respond in JSON array format ONLY:
[
  {{"source": "홍길동", "target": "AI Corp", "relation_type": "WORKS_FOR", "weight": 0.9, "description": "CEO로 재직"}}
]

Text:
{text}
"""


class OntologyBuilder:
    """Builds ontology from document text using LLM."""

    def __init__(self, llm_client: BaseLLMClient):
        self.llm = llm_client
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
        normalized = " ".join(normalized.split())
        return normalized

    @staticmethod
    def _is_low_signal_entity(name: str, description: str = "") -> bool:
        normalized = OntologyBuilder._normalize_entity_key(name)
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

    async def extract_ontology(
        self,
        text: str,
        topic: str = "",
        purpose: str = "",
        extract_entities: bool = True,
        extract_relations: bool = True,
        progress_callback: Callable[[int, str], Awaitable[None] | None] | None = None,
    ) -> OntologyResult:
        """Full ontology extraction pipeline."""
        result_id = str(uuid.uuid4())

        log.info("ontology_extraction_start", topic=topic, text_len=len(text))
        await self._report_progress(progress_callback, 5, "문서와 추출 파이프라인을 준비하는 중...")

        # Step 1: Extract schema (entity types + relation types)
        schema = await self._extract_schema(text, topic, purpose)
        log.info("schema_extracted",
                 entity_types=len(schema.entity_types),
                 relation_types=len(schema.relation_types))
        await self._report_progress(progress_callback, 20, "핵심 엔티티 타입과 관계 타입을 정리하는 중...")

        entities: list[Entity] = []
        relations: list[Relation] = []

        # Step 2: Extract entities
        if extract_entities:
            entities = await self._extract_entities(text, topic, purpose, schema, progress_callback)
            log.info("entities_extracted", count=len(entities))
        else:
            await self._report_progress(progress_callback, 45, "엔티티 추출을 건너뛰고 다음 단계로 이동 중...")

        # Step 3: Extract relations
        if extract_relations and entities:
            await self._report_progress(progress_callback, 55, "관계를 정리하기 위한 후보 엔티티를 확정하는 중...")
            relations = await self._extract_relations(text, topic, purpose, entities, schema, progress_callback)
            log.info("relations_extracted", count=len(relations))
        else:
            await self._report_progress(progress_callback, 75, "관계 추출 조건이 없어 후처리로 이동 중...")

        result = OntologyResult(
            id=result_id,
            schema_def=schema,
            entities=self._prune_entities(entities, relations),
            relations=relations,
            topic=topic,
            purpose=purpose,
        )

        self._results[result_id] = result
        await self._report_progress(progress_callback, 95, "엔티티와 관계를 정리해 최종 온톨로지를 만드는 중...")
        log.info("ontology_extraction_complete", id=result_id)
        return result

    def _prune_entities(self, entities: list[Entity], relations: list[Relation]) -> list[Entity]:
        """Keep graph-relevant entities and collapse obvious duplicates."""
        if not entities:
            return entities

        relation_ids = {r.source_id for r in relations} | {r.target_id for r in relations}
        deduped: dict[tuple[str, str], Entity] = {}

        for entity in entities:
            key = (entity.type.lower().strip(), self._normalize_entity_key(entity.name))
            if self._is_low_signal_entity(entity.name, entity.description):
                continue

            existing = deduped.get(key)
            if not existing:
                deduped[key] = entity
                continue

            existing_relation_backed = existing.id in relation_ids
            entity_relation_backed = entity.id in relation_ids
            if entity_relation_backed and not existing_relation_backed:
                deduped[key] = entity
                continue
            if existing_relation_backed and not entity_relation_backed:
                continue

            existing_score = len(existing.description or "") + len(existing.attributes or {}) * 10
            entity_score = len(entity.description or "") + len(entity.attributes or {}) * 10
            if entity_score > existing_score:
                deduped[key] = entity

        kept = list(deduped.values())
        if not relations:
            return kept

        relation_backed = [e for e in kept if e.id in relation_ids]
        if relation_backed:
            relation_keys = {(e.type.lower().strip(), self._normalize_entity_key(e.name)) for e in relation_backed}
            return [e for e in kept if (e.type.lower().strip(), self._normalize_entity_key(e.name)) in relation_keys]
        return kept

    async def _extract_schema(self, text: str, topic: str, purpose: str) -> OntologySchema:
        """Extract ontology schema from text."""
        prompt = SCHEMA_EXTRACTION_PROMPT.format(
            topic=topic or "General analysis",
            purpose=purpose or "Extract key concepts and relationships",
            text=text,  # full document
        )

        response = await self.llm.complete([
            {"role": "system", "content": "You are an ontology extraction expert. Always respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ], temperature=0.3, max_tokens=4096)

        try:
            data = self._parse_json(response)
            return OntologySchema(
                entity_types=[EntityType(**et) for et in data.get("entity_types", [])],
                relation_types=[RelationType(**rt) for rt in data.get("relation_types", [])],
            )
        except Exception as e:
            log.error("schema_parse_error", error=str(e), response=response[:500])
            return OntologySchema()

    async def _extract_entities(
        self,
        text: str,
        topic: str,
        purpose: str,
        schema: OntologySchema,
        progress_callback: Callable[[int, str], Awaitable[None] | None] | None = None,
    ) -> list[Entity]:
        """Extract entities from text using schema (병렬)."""
        entity_type_names = ", ".join(et.name for et in schema.entity_types)

        chunks = self._split_for_extraction(text, max_size=15000)
        all_entities: list[Entity] = []
        seen_names: set[str] = set()

        BATCH_SIZE = 5

        async def _extract_one(i: int, chunk: str) -> list[dict]:
            log.info("extracting_entities_chunk", chunk=i+1, total=len(chunks))
            prompt = ENTITY_EXTRACTION_PROMPT.format(
                topic=topic or "General",
                purpose=purpose or "Extract entities",
                entity_types=entity_type_names,
                text=chunk,
            )
            response = await self.llm.complete([
                {"role": "system", "content": "You are an entity extraction expert. Always respond with a valid JSON array only."},
                {"role": "user", "content": prompt},
            ], temperature=0.2, max_tokens=6000)
            try:
                items = self._parse_json(response)
                return items if isinstance(items, list) else []
            except Exception as e:
                log.warning("entity_parse_error", chunk=i, error=str(e))
                return []

        for batch_start in range(0, len(chunks), BATCH_SIZE):
            batch = [(batch_start + j, chunks[batch_start + j])
                     for j in range(min(BATCH_SIZE, len(chunks) - batch_start))]
            results = await asyncio.gather(
                *[_extract_one(i, chunk) for i, chunk in batch],
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, Exception):
                    log.warning("entity_batch_error", error=str(r))
                    continue
                for item in r:
                    name = item.get("name", "")
                    norm_name = self._normalize_entity_key(name)
                    if name and norm_name not in seen_names and not self._is_low_signal_entity(name, item.get("description", "")):
                        seen_names.add(norm_name)
                        all_entities.append(Entity(
                            name=name,
                            type=item.get("type", "Unknown"),
                            attributes=item.get("attributes", {}),
                            description=item.get("description", ""),
                        ))
            processed = min(batch_start + BATCH_SIZE, len(chunks))
            pct = 20 + int((processed / max(len(chunks), 1)) * 30)
            await self._report_progress(
                progress_callback,
                pct,
                f"엔티티 추출 중... ({processed}/{len(chunks)} 청크)",
            )

        return all_entities

    async def _extract_relations(
        self, text: str, topic: str, purpose: str,
        entities: list[Entity], schema: OntologySchema,
        progress_callback: Callable[[int, str], Awaitable[None] | None] | None = None,
    ) -> list[Relation]:
        """Extract relations between entities (병렬)."""
        entity_names = "\n".join(f"- {e.name} ({e.type})" for e in entities)
        relation_type_names = ", ".join(rt.name for rt in schema.relation_types)

        name_to_id = {e.name: e.id for e in entities}

        chunks = self._split_for_extraction(text, max_size=15000)
        all_relations: list[Relation] = []
        seen_pairs: set[tuple] = set()

        BATCH_SIZE = 5

        async def _extract_one(i: int, chunk: str) -> list[dict]:
            log.info("extracting_relations_chunk", chunk=i+1, total=len(chunks))
            prompt = RELATION_EXTRACTION_PROMPT.format(
                topic=topic or "General",
                purpose=purpose or "Extract relationships",
                entities=entity_names,
                relation_types=relation_type_names,
                text=chunk,
            )
            response = await self.llm.complete([
                {"role": "system", "content": "You are a relationship extraction expert. Always respond with a valid JSON array only."},
                {"role": "user", "content": prompt},
            ], temperature=0.2, max_tokens=6000)
            try:
                items = self._parse_json(response)
                return items if isinstance(items, list) else []
            except Exception as e:
                log.warning("relation_parse_error", chunk=i, error=str(e))
                return []

        for batch_start in range(0, len(chunks), BATCH_SIZE):
            batch = [(batch_start + j, chunks[batch_start + j])
                     for j in range(min(BATCH_SIZE, len(chunks) - batch_start))]
            results = await asyncio.gather(
                *[_extract_one(i, chunk) for i, chunk in batch],
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, Exception):
                    log.warning("relation_batch_error", error=str(r))
                    continue
                for item in r:
                    src = item.get("source", "")
                    tgt = item.get("target", "")
                    rel = item.get("relation_type", "RELATED_TO")
                    pair = (
                        self._normalize_entity_key(src),
                        self._normalize_entity_key(tgt),
                        rel,
                    )

                    if src in name_to_id and tgt in name_to_id and pair not in seen_pairs:
                        seen_pairs.add(pair)
                        all_relations.append(Relation(
                            source_id=name_to_id[src],
                            target_id=name_to_id[tgt],
                            relation_type=rel,
                            weight=float(item.get("weight", 0.5)),
                            description=item.get("description", ""),
                        ))
            processed = min(batch_start + BATCH_SIZE, len(chunks))
            pct = 55 + int((processed / max(len(chunks), 1)) * 35)
            await self._report_progress(
                progress_callback,
                pct,
                f"관계 추출 중... ({processed}/{len(chunks)} 청크)",
            )

        return all_relations

    def _split_for_extraction(self, text: str, max_size: int = 6000) -> list[str]:
        """Split text into processable chunks."""
        if len(text) <= max_size:
            return [text]
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + max_size, len(text))
            if end < len(text):
                for sep in ['\n\n', '. ', '\n']:
                    idx = text[start:end].rfind(sep)
                    if idx > max_size * 0.5:
                        end = start + idx + len(sep)
                        break
            chunks.append(text[start:end])
            start = end
        return chunks

    def _parse_json(self, text: str) -> dict | list:
        """Parse JSON from LLM response, handling markdown code blocks."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)

    def get_result(self, result_id: str) -> OntologyResult | None:
        return self._results.get(result_id)
