"""Higher-recall ontology extraction pipeline.

Key differences from the basic version:
- chunk-first extraction instead of whole-document single pass
- schema proposal + consolidation across chunks
- entity canonicalization with alias merging
- relation validation against known entities
- evidence spans kept in attributes
- batched merge to handle large entity lists
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict

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


SCHEMA_PROPOSAL_PROMPT = """You are building a reusable ontology for downstream simulation.

Topic: {topic}
Purpose: {purpose}

Text excerpt:
{chunk}

Extract as many distinct entity types and relation types as possible.
Return compact JSON only:
{{
  "entity_types": [
    {{
      "name": "Person",
      "description": "Human actors relevant to the topic",
      "attributes": ["role", "stance", "affiliation"]
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

SCHEMA_CONSOLIDATION_PROMPT = """You are consolidating ontology proposals from multiple document chunks.

Topic: {topic}
Purpose: {purpose}

Candidate schema proposals:
{proposals}

Tasks:
1. Merge only clear duplicates and synonyms — keep granularity high.
2. Prefer stable, reusable type names.
3. Keep ALL types that appear in at least one proposal.
4. Ensure relation types have clear source_type and target_type.

Return JSON only — include ALL entity and relation types found:
{{
  "entity_types": [...],
  "relation_types": [...]
}}
"""

CHUNK_EXTRACTION_PROMPT = """Extract ALL ontology instances from this chunk. Be thorough and inclusive.

Topic: {topic}
Purpose: {purpose}

Allowed entity types (extract as many as possible):
{entity_types}

Allowed relation types:
{relation_types}

Chunk text:
{chunk}

Return JSON only — include every entity and relation you can identify:
{{
  "entities": [
    {{
      "name": "entity name",
      "type": "allowed entity type",
      "description": "brief description grounded in this chunk",
      "attributes": {{"role": "value"}},
      "aliases": ["optional alias"],
      "evidence": "short supporting quote or phrase"
    }}
  ],
  "relations": [
    {{
      "source": "entity name",
      "target": "entity name",
      "relation_type": "allowed relation type",
      "weight": 0.8,
      "description": "grounded relationship description",
      "evidence": "short supporting quote or phrase"
    }}
  ]
}}
"""

ENTITY_MERGE_PROMPT = """You are deduplicating entities extracted from many document chunks.

Topic: {topic}

Candidate entities (may contain duplicates and near-duplicates):
{entities}

Instructions:
- Merge only genuine duplicates, aliases, and near-duplicates.
- Keep all distinct entities — do NOT reduce the count aggressively.
- Preserve the most informative description and combine attributes.
- If unsure whether two entities are the same, keep them separate.

Return a JSON array of ALL canonical entities:
[
  {{
    "canonical_name": "OpenAI",
    "type": "Organization",
    "description": "AI company focused on safe AGI development",
    "attributes": {{"role": "lab", "founded": "2015"}},
    "aliases": ["Open AI"],
    "source_names": ["OpenAI", "Open AI"]
  }}
]
"""

RELATION_REVIEW_PROMPT = """You are reviewing extracted relations.

Known canonical entities:
{entities}

Candidate relations:
{relations}

Rules:
1. Keep only relations whose source and target both map to known entities.
2. Remove exact duplicates.
3. Keep relation_type unchanged if valid.
4. When source/target names are aliases, map to the canonical name.

Return JSON only — keep as many valid relations as possible:
[
  {{
    "source": "canonical source name",
    "target": "canonical target name",
    "relation_type": "RELATION",
    "weight": 0.7,
    "description": "..."
  }}
]
"""

# Max raw entities to send in a single merge call before batching
_MERGE_BATCH_SIZE = 60


class OntologyBuilderGPT:
    """Improved ontology extraction with higher recall and quality."""

    def __init__(self, llm_client: BaseLLMClient, chunk_size: int = 2800, overlap: int = 280):
        self.llm = llm_client
        self.chunker = TextChunker(chunk_size=chunk_size, overlap=overlap)
        self._results: dict[str, OntologyResult] = {}

    # ── Public interface (same as OntologyBuilder) ────────────────────────────

    async def extract_ontology(
        self,
        text: str,
        topic: str = "",
        purpose: str = "",
        extract_entities: bool = True,
        extract_relations: bool = True,
    ) -> OntologyResult:
        result_id = str(uuid.uuid4())
        topic = topic or "General analysis"
        purpose = purpose or "Build a grounded ontology for simulation"

        chunks = self.chunker.split(text)
        log.info("ontology_gpt_start", topic=topic, chunks=len(chunks), text_len=len(text))

        schema = await self._extract_schema(chunks, topic, purpose)
        log.info("ontology_gpt_schema", entity_types=len(schema.entity_types),
                 relation_types=len(schema.relation_types))

        entities: list[Entity] = []
        relations: list[Relation] = []

        if extract_entities:
            chunk_payloads = await self._extract_chunk_payloads(chunks, topic, purpose, schema)
            entities = await self._merge_entities(chunk_payloads, topic)
            log.info("ontology_gpt_entities", count=len(entities))
            if extract_relations and entities:
                relations = await self._review_relations(chunk_payloads, entities)
                log.info("ontology_gpt_relations", count=len(relations))

        result = OntologyResult(
            id=result_id,
            schema_def=schema,
            entities=entities,
            relations=relations,
            topic=topic,
            purpose=purpose,
        )
        self._results[result_id] = result
        return result

    def get_result(self, result_id: str) -> OntologyResult | None:
        return self._results.get(result_id)

    # ── Schema extraction ─────────────────────────────────────────────────────

    async def _extract_schema(self, chunks: list[TextChunk], topic: str, purpose: str) -> OntologySchema:
        # Sample evenly across the document (up to 6 chunks)
        step = max(1, len(chunks) // 6)
        sampled = chunks[::step][:6]
        proposals: list[dict] = []

        for chunk in sampled:
            response = await self.llm.complete(
                [
                    {"role": "system", "content": "You design ontologies. Respond with valid JSON only."},
                    {"role": "user", "content": SCHEMA_PROPOSAL_PROMPT.format(
                        topic=topic, purpose=purpose, chunk=chunk.text[:3200],
                    )},
                ],
                temperature=0.2,
                max_tokens=2000,
            )
            try:
                proposals.append(self._parse_json(response))
            except Exception as exc:
                log.warning("ontology_gpt_proposal_failed", error=str(exc)[:120])

        if not proposals:
            return OntologySchema()

        response = await self.llm.complete(
            [
                {"role": "system", "content": "Consolidate ontology proposals. Respond with valid JSON only."},
                {"role": "user", "content": SCHEMA_CONSOLIDATION_PROMPT.format(
                    topic=topic, purpose=purpose,
                    proposals=json.dumps(proposals, ensure_ascii=False, indent=2),
                )},
            ],
            temperature=0.1,
            max_tokens=3000,
        )

        try:
            data = self._parse_json(response)
            return OntologySchema(
                entity_types=[EntityType(**item) for item in data.get("entity_types", [])],
                relation_types=[RelationType(**item) for item in data.get("relation_types", [])],
            )
        except Exception as exc:
            log.error("ontology_gpt_schema_consolidation_failed", error=str(exc)[:120])
            return OntologySchema()

    # ── Per-chunk entity+relation extraction ─────────────────────────────────

    async def _extract_chunk_payloads(
        self,
        chunks: list[TextChunk],
        topic: str,
        purpose: str,
        schema: OntologySchema,
    ) -> list[dict]:
        entity_types = ", ".join(item.name for item in schema.entity_types) or "Entity"
        relation_types = ", ".join(item.name for item in schema.relation_types) or "RELATED_TO"
        payloads: list[dict] = []

        for chunk in chunks:
            response = await self.llm.complete(
                [
                    {"role": "system", "content": "Extract grounded entities and relations. Respond with valid JSON only."},
                    {"role": "user", "content": CHUNK_EXTRACTION_PROMPT.format(
                        topic=topic, purpose=purpose,
                        entity_types=entity_types,
                        relation_types=relation_types,
                        chunk=chunk.text[:3500],
                    )},
                ],
                temperature=0.2,
                max_tokens=3000,
            )
            try:
                data = self._parse_json(response)
                data["_chunk_index"] = chunk.index
                payloads.append(data)
            except Exception as exc:
                log.warning("ontology_gpt_chunk_parse_failed", chunk=chunk.index, error=str(exc)[:120])

        return payloads

    # ── Entity merge (batched for large entity sets) ──────────────────────────

    async def _merge_entities(self, payloads: list[dict], topic: str) -> list[Entity]:
        raw_entities: list[dict] = []
        by_name: dict[str, list[dict]] = defaultdict(list)

        for payload in payloads:
            chunk_index = payload.get("_chunk_index")
            for entity in payload.get("entities", []):
                enriched = dict(entity)
                attrs = dict(enriched.get("attributes", {}))
                evidence = enriched.get("evidence")
                if evidence:
                    attrs.setdefault("evidence", []).append(
                        {"chunk_index": chunk_index, "text": evidence}
                    )
                enriched["attributes"] = attrs
                raw_entities.append(enriched)
                name = str(enriched.get("name", "")).strip()
                if name:
                    by_name[name.lower()].append(enriched)

        if not raw_entities:
            return []

        log.info("ontology_gpt_raw_entities", count=len(raw_entities))

        # Batch merge: split into chunks of _MERGE_BATCH_SIZE
        batches = [
            raw_entities[i: i + _MERGE_BATCH_SIZE]
            for i in range(0, len(raw_entities), _MERGE_BATCH_SIZE)
        ]
        all_merged: list[dict] = []

        for batch_idx, batch in enumerate(batches):
            response = await self.llm.complete(
                [
                    {"role": "system", "content": "Merge extracted entities into canonical entities. Respond with valid JSON only."},
                    {"role": "user", "content": ENTITY_MERGE_PROMPT.format(
                        topic=topic,
                        entities=json.dumps(batch, ensure_ascii=False, indent=2),
                    )},
                ],
                temperature=0.1,
                max_tokens=8192,
            )
            try:
                merged = self._parse_json(response)
                if isinstance(merged, list):
                    all_merged.extend(merged)
            except Exception as exc:
                log.warning("ontology_gpt_entity_merge_failed", batch=batch_idx, error=str(exc)[:120])
                # Fallback: use raw entities from this batch
                for e in batch:
                    name = str(e.get("name", "")).strip()
                    if name:
                        all_merged.append({
                            "canonical_name": e.get("name"),
                            "type": e.get("type", "Entity"),
                            "description": e.get("description", ""),
                            "attributes": e.get("attributes", {}),
                        })

        if not all_merged:
            # Final fallback: deduplicate by name only
            return [
                Entity(
                    name=candidates[0].get("name", "Unknown"),
                    type=candidates[0].get("type", "Entity"),
                    description=candidates[0].get("description", ""),
                    attributes=candidates[0].get("attributes", {}),
                )
                for candidates in by_name.values()
            ]

        # Deduplicate across batches by canonical_name
        seen_canonical: set[str] = set()
        merged_entities: list[Entity] = []

        for item in all_merged:
            canonical = (item.get("canonical_name") or item.get("name") or "Unknown").strip()
            if canonical.lower() in seen_canonical:
                continue
            seen_canonical.add(canonical.lower())

            attrs = dict(item.get("attributes", {}))
            if item.get("aliases"):
                attrs["aliases"] = item["aliases"]
            if item.get("source_names"):
                attrs["source_names"] = item["source_names"]

            merged_entities.append(Entity(
                name=canonical,
                type=item.get("type", "Entity"),
                description=item.get("description", ""),
                attributes=attrs,
            ))

        return merged_entities

    # ── Relation review ───────────────────────────────────────────────────────

    async def _review_relations(self, payloads: list[dict], entities: list[Entity]) -> list[Relation]:
        if not entities:
            return []

        # Build lookup: name + aliases → entity
        canonical_map: dict[str, Entity] = {}
        for entity in entities:
            canonical_map[entity.name.lower()] = entity
            for alias in entity.attributes.get("aliases", []):
                canonical_map[str(alias).lower()] = entity
            for src in entity.attributes.get("source_names", []):
                canonical_map[str(src).lower()] = entity

        raw_relations: list[dict] = []
        for payload in payloads:
            chunk_index = payload.get("_chunk_index")
            for relation in payload.get("relations", []):
                enriched = dict(relation)
                if relation.get("evidence"):
                    enriched["evidence_meta"] = {"chunk_index": chunk_index, "text": relation["evidence"]}
                raw_relations.append(enriched)

        if not raw_relations:
            return []

        response = await self.llm.complete(
            [
                {"role": "system", "content": "Review and deduplicate relations. Respond with valid JSON only."},
                {"role": "user", "content": RELATION_REVIEW_PROMPT.format(
                    entities=json.dumps(
                        [{"name": e.name, "type": e.type} for e in entities],
                        ensure_ascii=False, indent=2,
                    ),
                    relations=json.dumps(raw_relations, ensure_ascii=False, indent=2),
                )},
            ],
            temperature=0.1,
            max_tokens=8192,
        )

        try:
            reviewed = self._parse_json(response)
            if not isinstance(reviewed, list):
                reviewed = []
        except Exception as exc:
            log.warning("ontology_gpt_relation_review_failed", error=str(exc)[:120])
            reviewed = raw_relations

        deduped: list[Relation] = []
        seen: set[tuple[str, str, str]] = set()

        for item in reviewed:
            src_name = str(item.get("source", "")).lower().strip()
            tgt_name = str(item.get("target", "")).lower().strip()
            rel_type = str(item.get("relation_type", "RELATED_TO")).upper()

            src = canonical_map.get(src_name)
            tgt = canonical_map.get(tgt_name)
            key = (src_name, tgt_name, rel_type)

            if not src or not tgt or key in seen:
                continue

            seen.add(key)
            deduped.append(Relation(
                source_id=src.id,
                target_id=tgt.id,
                relation_type=rel_type,
                weight=float(item.get("weight", 0.5)),
                description=item.get("description", ""),
            ))

        return deduped

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_json(self, text: str) -> dict | list:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)
