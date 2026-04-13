"""
graphiti_extractor.py

Graphiti-based ontology extractor that mirrors the OntologyBuilder interface.
"""

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, create_model

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.embedder.client import EmbedderClient, EmbedderConfig
from graphiti_core.llm_client import LLMClient
from graphiti_core.llm_client.config import LLMConfig as GraphitiLLMConfig
from graphiti_core.llm_client.errors import RateLimitError as GraphitiRateLimitError
from graphiti_core.llm_client.openai_client import OpenAIClient as GraphitiOpenAI
from graphiti_core.nodes import EpisodeType

from config import settings
from db.neo4j_client import neo4j_client
from llm.factory import get_llm_client
from models.ontology import (
    Entity,
    EntityType,
    OntologyResult,
    OntologySchema,
    Relation,
    RelationType,
)
from utils.logger import log


SCHEMA_PROMPT = """You are designing a lightweight ontology schema for a knowledge graph.

Topic: {topic}
Purpose: {purpose}

Document excerpt:
{excerpt}

Design entity and relation types that can be extracted from this document.

Rules:
- Return 5 to 8 entity types.
- Always include "Person" and "Organization".
- Entity types must describe concrete actors or things that appear in the text.
- Return 4 to 8 relation types in UPPER_SNAKE_CASE.
- Each entity type may define up to 5 Optional[str] attributes.
- Do not use reserved properties: name, uuid, group_id, summary, created_at

Return JSON only:
{{
  "entity_types": [
    {{
      "name": "TypeName",
      "description": "What this entity type represents",
      "attributes": [
        {{"name": "attribute_name", "description": "Attribute description"}}
      ]
    }}
  ],
  "edge_types": [
    {{
      "name": "RELATION_NAME",
      "description": "What this relation means",
      "source_types": ["TypeName"],
      "target_types": ["TypeName"]
    }}
  ]
}}
"""


class _NoOpCrossEncoder(CrossEncoderClient):
    """Keeps Graphiti from initializing the default OpenAI reranker."""

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        return [(passage, 0.0) for passage in passages]


class _LocalEmbedderConfig(EmbedderConfig):
    embedding_dim: int = Field(default=384, frozen=True)


class _LocalEmbedder(EmbedderClient):
    """Fallback local embedder for non-OpenAI providers."""

    def __init__(self):
        self.config = _LocalEmbedderConfig()
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer("all-MiniLM-L6-v2")

    async def create(self, input_data: "str | list[str]") -> list[float]:
        self._load()
        loop = asyncio.get_event_loop()
        text = input_data if isinstance(input_data, str) else input_data[0]
        embedding: list[float] = await loop.run_in_executor(
            None, lambda: self._model.encode([text])[0].tolist()
        )
        return embedding

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        self._load()
        loop = asyncio.get_event_loop()
        embeddings: list[list[float]] = await loop.run_in_executor(
            None, lambda: self._model.encode(input_data_list).tolist()
        )
        return embeddings


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: Optional[str] = None


class GraphitiExtractor:
    """
    Graphiti-based ontology extractor.

    This keeps the public shape close to OntologyBuilder.extract_ontology().
    """

    CHUNK_SIZE = 6000
    CHUNK_OVERLAP = 200
    MAX_TEXT_LENGTH = 18000
    EPISODE_DELAY = 2.0

    _SKIP_PROPS = frozenset(
        {
            "uuid",
            "name",
            "group_id",
            "summary",
            "created_at",
            "labels",
            "name_embedding",
            "fact_embedding",
        }
    )

    def __init__(self, llm_cfg: LLMConfig):
        self.llm_cfg = llm_cfg
        self._graphiti: Optional[Graphiti] = None
        self.group_id: str = ""

    async def _complete(self, prompt: str) -> str:
        client = get_llm_client(
            provider=self.llm_cfg.provider,
            api_key=self.llm_cfg.api_key,
            model=self.llm_cfg.model,
            base_url=self.llm_cfg.base_url,
            feature="graph_extract",
        )
        return await client.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=4096,
        )

    @staticmethod
    def _parse_json(text: str) -> Any:
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return json.loads(text)

    async def _design_schema(self, text: str, topic: str, purpose: str) -> dict:
        excerpt = text[:4000]
        raw = await self._complete(
            SCHEMA_PROMPT.format(topic=topic, purpose=purpose, excerpt=excerpt)
        )
        try:
            schema = self._parse_json(raw)
        except Exception as exc:
            log.warning("graphiti_schema_parse_error", error=str(exc))
            schema = {"entity_types": [], "edge_types": []}

        existing = {entity_type["name"] for entity_type in schema.get("entity_types", [])}
        for fallback in ("Organization", "Person"):
            if fallback not in existing:
                schema.setdefault("entity_types", []).append(
                    {
                        "name": fallback,
                        "description": f"Generic {fallback.lower()}",
                        "attributes": [],
                    }
                )
        return schema

    @staticmethod
    def _build_models(
        schema: dict,
    ) -> tuple[
        dict[str, type[BaseModel]],
        dict[str, type[BaseModel]],
        dict[tuple[str, str], list[str]],
    ]:
        entity_models: dict[str, type[BaseModel]] = {}
        for entity_type in schema.get("entity_types", []):
            fields: dict[str, Any] = {}
            for attr in entity_type.get("attributes", []):
                fields[attr["name"]] = (
                    Optional[str],
                    Field(None, description=attr.get("description", "")),
                )
            cls = create_model(entity_type["name"], **fields)
            cls.__doc__ = entity_type.get("description", entity_type["name"])
            entity_models[entity_type["name"]] = cls

        edge_models: dict[str, type[BaseModel]] = {}
        for edge_type in schema.get("edge_types", []):
            cls = create_model(edge_type["name"])
            cls.__doc__ = edge_type.get("description", edge_type["name"])
            edge_models[edge_type["name"]] = cls

        edge_type_map: dict[tuple[str, str], list[str]] = {}
        for edge_type in schema.get("edge_types", []):
            for source_type in edge_type.get("source_types", []):
                for target_type in edge_type.get("target_types", []):
                    edge_type_map.setdefault((source_type, target_type), []).append(
                        edge_type["name"]
                    )

        return entity_models, edge_models, edge_type_map

    def _make_llm_client(self) -> LLMClient:
        cfg = GraphitiLLMConfig(
            api_key=self.llm_cfg.api_key,
            model=self.llm_cfg.model,
            base_url=self.llm_cfg.base_url,
        )
        provider = self.llm_cfg.provider
        if provider == "anthropic":
            from graphiti_core.llm_client.anthropic_client import AnthropicClient

            return AnthropicClient(config=cfg)
        if provider == "gemini":
            from graphiti_core.llm_client.gemini_client import GeminiClient

            return GeminiClient(config=cfg)
        return GraphitiOpenAI(config=cfg, reasoning="low")

    def _make_embedder(self) -> EmbedderClient:
        if self.llm_cfg.provider == "openai":
            from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig

            return OpenAIEmbedder(config=OpenAIEmbedderConfig(api_key=self.llm_cfg.api_key))
        return _LocalEmbedder()

    async def _init_graphiti(self):
        self.group_id = str(uuid.uuid4())
        self._graphiti = Graphiti(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            llm_client=self._make_llm_client(),
            embedder=self._make_embedder(),
            cross_encoder=_NoOpCrossEncoder(),
        )
        await self._graphiti.build_indices_and_constraints()
        log.info("graphiti_init_ok", group_id=self.group_id)

    def _chunks(self, text: str) -> list[str]:
        result: list[str] = []
        start = 0
        while start < len(text):
            result.append(text[start : start + self.CHUNK_SIZE])
            start += self.CHUNK_SIZE - self.CHUNK_OVERLAP
        return result

    async def _feed_episodes(
        self,
        text: str,
        topic: str,
        entity_models: dict,
        edge_models: dict,
        edge_type_map: dict,
    ) -> int:
        chunks = self._chunks(text)
        log.info("graphiti_feed_start", total_chunks=len(chunks))

        for i, chunk in enumerate(chunks):
            try:
                await self._graphiti.add_episode(
                    name=f"{topic}_ep{i}",
                    episode_body=chunk,
                    source=EpisodeType.text,
                    source_description=topic,
                    reference_time=datetime.now(timezone.utc),
                    group_id=self.group_id,
                    entity_types=entity_models or None,
                    edge_types=edge_models or None,
                    edge_type_map=edge_type_map or None,
                )
            except GraphitiRateLimitError:
                log.warning("graphiti_rate_limit_partial", completed=i, total=len(chunks))
                return i

            log.info("graphiti_ep_done", chunk=i + 1, total=len(chunks))
            if i < len(chunks) - 1:
                await asyncio.sleep(self.EPISODE_DELAY)

        return len(chunks)

    async def _fetch(self) -> tuple[list[dict], list[dict]]:
        gid = self.group_id

        nodes = await neo4j_client.execute(
            "MATCH (n:Entity {group_id: $gid}) RETURN n, labels(n) AS lbls",
            {"gid": gid},
        )
        edges = await neo4j_client.execute(
            """
            MATCH (s:Entity {group_id: $gid})-[e:RELATES_TO]->(t:Entity {group_id: $gid})
            RETURN s.uuid AS src,
                   t.uuid AS tgt,
                   e.name AS rel_name,
                   e.fact AS fact
            """,
            {"gid": gid},
        )
        return nodes, edges

    def _convert(
        self,
        schema: dict,
        nodes_raw: list[dict],
        edges_raw: list[dict],
        topic: str,
        purpose: str,
    ) -> OntologyResult:
        entity_types = [
            EntityType(
                name=entity_type["name"],
                description=entity_type.get("description", ""),
                attributes=[attr["name"] for attr in entity_type.get("attributes", [])],
            )
            for entity_type in schema.get("entity_types", [])
        ]
        relation_types = [
            RelationType(
                name=edge_type["name"],
                description=edge_type.get("description", ""),
                source_type=(edge_type.get("source_types") or [""])[0],
                target_type=(edge_type.get("target_types") or [""])[0],
            )
            for edge_type in schema.get("edge_types", [])
        ]

        uuid_map: dict[str, str] = {}
        entities: list[Entity] = []
        for row in nodes_raw:
            node = row.get("n", row)
            props = dict(node) if hasattr(node, "items") else node
            entity_id = str(uuid.uuid4())
            node_uuid = props.get("uuid", entity_id)
            uuid_map[node_uuid] = entity_id

            labels: list[str] = row.get("lbls") or props.get("labels") or []
            entity_type = next(
                (label for label in labels if label not in ("Entity", "EntityNode", "Node")),
                "Entity",
            )
            entities.append(
                Entity(
                    id=entity_id,
                    name=props.get("name", ""),
                    type=entity_type,
                    description=props.get("summary", ""),
                    attributes={
                        key: value
                        for key, value in props.items()
                        if key not in self._SKIP_PROPS and not isinstance(value, (list, bytes))
                    },
                )
            )

        relations: list[Relation] = []
        for row in edges_raw:
            source_id = uuid_map.get(row.get("src", ""))
            target_id = uuid_map.get(row.get("tgt", ""))
            if not source_id or not target_id:
                continue
            relations.append(
                Relation(
                    source_id=source_id,
                    target_id=target_id,
                    relation_type=row.get("rel_name") or "RELATED_TO",
                    weight=1.0,
                    description=row.get("fact") or "",
                )
            )

        return OntologyResult(
            schema_def=OntologySchema(
                entity_types=entity_types,
                relation_types=relation_types,
            ),
            entities=entities,
            relations=relations,
            topic=topic,
            purpose=purpose,
        )

    async def extract_ontology(
        self,
        text: str,
        topic: str = "",
        purpose: str = "",
        **_kwargs,
    ) -> OntologyResult:
        log.info("graphiti_extract_start", topic=topic)

        if len(text) > self.MAX_TEXT_LENGTH:
            log.info(
                "graphiti_text_truncated",
                original=len(text),
                truncated=self.MAX_TEXT_LENGTH,
            )
            text = text[: self.MAX_TEXT_LENGTH]

        schema = await self._design_schema(text, topic, purpose)
        entity_models, edge_models, edge_type_map = self._build_models(schema)
        log.info(
            "graphiti_schema_ready",
            entity_types=len(entity_models),
            edge_types=len(edge_models),
        )

        await self._init_graphiti()

        completed = await self._feed_episodes(
            text, topic, entity_models, edge_models, edge_type_map
        )
        if completed == 0:
            raise RuntimeError("Rate limit exceeded before any episode was processed.")

        nodes_raw, edges_raw = await self._fetch()
        log.info("graphiti_fetched", nodes=len(nodes_raw), edges=len(edges_raw))

        result = self._convert(schema, nodes_raw, edges_raw, topic, purpose)
        log.info(
            "graphiti_extract_done",
            entities=len(result.entities),
            relations=len(result.relations),
        )
        return result

    async def close(self):
        if self._graphiti:
            await self._graphiti.close()
