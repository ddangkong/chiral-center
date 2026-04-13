"""GraphRAG engine — entity extraction, community detection, summarization, and RAG query.

Implements the core Microsoft GraphRAG concepts:
1. Extract entities & relations from text chunks via LLM
2. Build a networkx graph and detect communities (Leiden/Louvain)
3. Summarize each community via LLM
4. Answer questions via Local Search (entity-focused) or Global Search (community-based)
"""
import json
import pathlib
import asyncio
from typing import Optional

from llm.base import BaseLLMClient
from models.graphrag import (
    GraphRAGIndex, GraphRAGStatus, GraphRAGEntity, GraphRAGRelation,
    Community, GraphRAGQueryResult,
)
from utils.logger import log

_DATA_DIR = pathlib.Path(__file__).parent.parent / "data" / "graphrag"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Prompts ──────────────────────────────────────────────────────────────

ENTITY_EXTRACTION_PROMPT = """Extract all entities and relationships from the following text.
Focus on people, organizations, products, events, locations, concepts, and their connections.

Text:
{text}

Return valid JSON:
{{
  "entities": [
    {{"name": "Entity Name", "type": "Person|Organization|Product|Event|Location|Concept|Other", "description": "Brief description"}}
  ],
  "relations": [
    {{"source": "Entity A", "target": "Entity B", "description": "How they are related", "weight": 0.8}}
  ]
}}

Rules:
- Entity names should be normalized (consistent capitalization)
- Deduplicate entities with different surface forms referring to the same thing
- Weight reflects relationship strength (0.0 to 1.0)
- Include at least the most important entities and their key relationships
"""

COMMUNITY_SUMMARY_PROMPT = """You are analyzing a community of related entities in a knowledge graph.

Community entities:
{entities}

Relationships within this community:
{relations}

Write a comprehensive summary of this community in Korean (한국어).
Include:
1. A short title (5-10 words) describing the community theme
2. A 2-4 sentence summary explaining the key entities, their roles, and how they relate

Return valid JSON:
{{
  "title": "커뮤니티 제목",
  "summary": "커뮤니티 요약 내용 (2-4문장, 한국어)"
}}
"""

LOCAL_SEARCH_PROMPT = """You are a knowledge assistant. Answer the user's question using ONLY the provided context.

Question: {query}

Relevant entities:
{entities}

Relevant relationships:
{relations}

Relevant community summaries:
{communities}

Instructions:
- Answer in Korean (한국어)
- Be factual and cite specific entities/relationships from the context
- If the context doesn't contain enough information, say so honestly
- Be concise but thorough (3-6 sentences)

Answer:"""

GLOBAL_SEARCH_PROMPT = """You are a knowledge assistant answering a high-level question using community-level summaries.

Question: {query}

Community summaries (from most to least relevant):
{community_summaries}

Instructions:
- Synthesize information across multiple communities to answer comprehensively
- Answer in Korean (한국어)
- Reference specific themes and patterns across communities
- Be thorough (4-8 sentences)

Answer:"""


class GraphRAGEngine:
    """GraphRAG indexing and query engine."""

    def __init__(self, llm_client: BaseLLMClient):
        self.llm = llm_client
        self._indices: dict[str, GraphRAGIndex] = {}

    # ── Indexing Pipeline ────────────────────────────────────────────────

    async def index_documents(
        self,
        ontology_id: str,
        text_chunks: list[str],
        progress_callback=None,
    ) -> GraphRAGIndex:
        """Full indexing pipeline: extract → build graph → communities → summarize."""
        idx = GraphRAGIndex(ontology_id=ontology_id, status=GraphRAGStatus.INDEXING)
        idx.text_chunks = text_chunks
        self._indices[idx.id] = idx

        BATCH_SIZE = 5  # 동시 LLM 호출 수

        try:
            # Step 1: Extract entities and relations from each chunk (병렬)
            if progress_callback:
                await progress_callback("entities", 0, len(text_chunks))

            all_entities: list[GraphRAGEntity] = []
            all_relations: list[GraphRAGRelation] = []
            done_count = 0

            for batch_start in range(0, len(text_chunks), BATCH_SIZE):
                batch = text_chunks[batch_start:batch_start + BATCH_SIZE]
                results = await asyncio.gather(
                    *[self._extract_from_chunk(chunk) for chunk in batch],
                    return_exceptions=True,
                )
                for r in results:
                    if isinstance(r, Exception):
                        log.warning("graphrag_batch_error", error=str(r))
                        continue
                    entities, relations = r
                    all_entities.extend(entities)
                    all_relations.extend(relations)
                done_count += len(batch)
                if progress_callback:
                    await progress_callback("entities", done_count, len(text_chunks))
                await asyncio.sleep(0.1)

            # Deduplicate entities by name
            entity_map: dict[str, GraphRAGEntity] = {}
            for e in all_entities:
                key = e.name.lower().strip()
                if key not in entity_map or len(e.description) > len(entity_map[key].description):
                    entity_map[key] = e
            idx.entities = list(entity_map.values())

            # Deduplicate relations
            rel_map: dict[str, GraphRAGRelation] = {}
            for r in all_relations:
                key = f"{r.source.lower()}|{r.target.lower()}|{r.description[:50]}"
                if key not in rel_map or r.weight > rel_map[key].weight:
                    rel_map[key] = r
            idx.relations = list(rel_map.values())

            log.info("graphrag_extraction_done",
                     entities=len(idx.entities), relations=len(idx.relations))

            # Step 2: Community detection
            if progress_callback:
                await progress_callback("communities", 0, 1)

            idx.communities = self._detect_communities(idx.entities, idx.relations)

            log.info("graphrag_communities_detected", count=len(idx.communities))

            # Step 3: Summarize communities (병렬)
            if progress_callback:
                await progress_callback("summaries", 0, len(idx.communities))

            done_summaries = 0
            for batch_start in range(0, len(idx.communities), BATCH_SIZE):
                batch = idx.communities[batch_start:batch_start + BATCH_SIZE]
                await asyncio.gather(
                    *[self._summarize_community(c, idx.entities, idx.relations) for c in batch],
                    return_exceptions=True,
                )
                done_summaries += len(batch)
                if progress_callback:
                    await progress_callback("summaries", done_summaries, len(idx.communities))
                await asyncio.sleep(0.1)

            idx.status = GraphRAGStatus.READY
            self._save_index(idx)

            log.info("graphrag_index_complete", index_id=idx.id,
                     entities=len(idx.entities), communities=len(idx.communities))

        except Exception as e:
            idx.status = GraphRAGStatus.ERROR
            idx.error = str(e)
            log.error("graphrag_index_error", error=str(e))
            raise

        return idx

    async def _extract_from_chunk(self, text: str) -> tuple[list[GraphRAGEntity], list[GraphRAGRelation]]:
        """Extract entities and relations from a single text chunk."""
        prompt = ENTITY_EXTRACTION_PROMPT.format(text=text[:6000])

        try:
            response = await self.llm.complete([
                {"role": "system", "content": "You are an entity extraction system. Return valid JSON only."},
                {"role": "user", "content": prompt},
            ], temperature=0.1, max_tokens=2048)

            data = self._parse_json(response)
            entities = [
                GraphRAGEntity(
                    name=e["name"],
                    type=e.get("type", "Other"),
                    description=e.get("description", ""),
                )
                for e in data.get("entities", [])
                if e.get("name")
            ]
            relations = [
                GraphRAGRelation(
                    source=r["source"],
                    target=r["target"],
                    description=r.get("description", ""),
                    weight=float(r.get("weight", 0.5)),
                )
                for r in data.get("relations", [])
                if r.get("source") and r.get("target")
            ]
            return entities, relations

        except Exception as e:
            log.warning("graphrag_chunk_extraction_error", error=str(e))
            return [], []

    def _detect_communities(
        self,
        entities: list[GraphRAGEntity],
        relations: list[GraphRAGRelation],
    ) -> list[Community]:
        """Detect communities using networkx + Louvain algorithm."""
        try:
            import networkx as nx
        except ImportError:
            log.warning("networkx not installed, returning single community")
            return [Community(
                id=0, entities=[e.name for e in entities], level=0,
                weight=1.0,
            )]

        G = nx.Graph()
        entity_names = {e.name.lower(): e.name for e in entities}

        for e in entities:
            G.add_node(e.name.lower(), label=e.name, type=e.type)

        for r in relations:
            src = r.source.lower()
            tgt = r.target.lower()
            if src in entity_names and tgt in entity_names:
                G.add_edge(src, tgt, weight=r.weight, description=r.description)

        if len(G.nodes) == 0:
            return []

        # Use Louvain community detection
        try:
            communities_dict = nx.community.louvain_communities(G, weight='weight', seed=42)
        except Exception:
            # Fallback: connected components
            communities_dict = list(nx.connected_components(G))

        result = []
        for i, members in enumerate(communities_dict):
            member_names = [entity_names.get(m, m) for m in members]
            weight = sum(1 for r in relations
                         if r.source.lower() in members and r.target.lower() in members)
            result.append(Community(
                id=i,
                entities=member_names,
                level=0,
                weight=float(weight),
            ))

        # Assign community IDs back to entities
        for community in result:
            for e in entities:
                if e.name in community.entities:
                    e.community_id = community.id

        # Sort by weight (most connected first)
        result.sort(key=lambda c: c.weight, reverse=True)
        return result

    async def _summarize_community(
        self,
        community: Community,
        all_entities: list[GraphRAGEntity],
        all_relations: list[GraphRAGRelation],
    ):
        """Generate LLM summary for a community."""
        community_entities = [e for e in all_entities if e.name in community.entities]
        community_relations = [
            r for r in all_relations
            if r.source in community.entities and r.target in community.entities
        ]

        entities_text = "\n".join(
            f"- {e.name} ({e.type}): {e.description}" for e in community_entities
        )
        relations_text = "\n".join(
            f"- {r.source} -> {r.target}: {r.description}" for r in community_relations
        )

        if not entities_text:
            community.title = f"Community {community.id}"
            community.summary = "No entities found."
            return

        prompt = COMMUNITY_SUMMARY_PROMPT.format(
            entities=entities_text,
            relations=relations_text or "(No internal relations)",
        )

        try:
            response = await self.llm.complete([
                {"role": "system", "content": "You are a knowledge graph analyst. Return valid JSON only."},
                {"role": "user", "content": prompt},
            ], temperature=0.3, max_tokens=512)

            data = self._parse_json(response)
            community.title = data.get("title", f"Community {community.id}")
            community.summary = data.get("summary", "")
        except Exception as e:
            community.title = f"Community {community.id}"
            community.summary = f"Summary generation failed: {e}"

    # ── Query Pipeline ───────────────────────────────────────────────────

    async def local_search(self, index_id: str, query: str) -> GraphRAGQueryResult:
        """Entity-focused search: find relevant entities → their communities → answer."""
        idx = self._get_index(index_id)
        if not idx:
            return GraphRAGQueryResult(answer="인덱스를 찾을 수 없습니다.", search_type="local")

        # Find relevant entities by keyword matching
        query_lower = query.lower()
        scored_entities = []
        for e in idx.entities:
            score = 0
            if query_lower in e.name.lower():
                score += 3
            if query_lower in e.description.lower():
                score += 1
            for word in query_lower.split():
                if word in e.name.lower():
                    score += 2
                if word in e.description.lower():
                    score += 0.5
            if score > 0:
                scored_entities.append((e, score))

        scored_entities.sort(key=lambda x: x[1], reverse=True)
        top_entities = [e for e, _ in scored_entities[:10]]

        # If no keyword matches, use all entities (let LLM figure it out)
        if not top_entities:
            top_entities = idx.entities[:15]

        # Get related relations
        entity_names = {e.name for e in top_entities}
        relevant_relations = [
            r for r in idx.relations
            if r.source in entity_names or r.target in entity_names
        ][:20]

        # Get relevant communities
        community_ids = {e.community_id for e in top_entities if e.community_id >= 0}
        relevant_communities = [c for c in idx.communities if c.id in community_ids][:5]

        # Build context and query LLM
        entities_text = "\n".join(
            f"- {e.name} ({e.type}): {e.description}" for e in top_entities
        )
        relations_text = "\n".join(
            f"- {r.source} -> {r.target}: {r.description}" for r in relevant_relations
        )
        communities_text = "\n".join(
            f"- [{c.title}]: {c.summary}" for c in relevant_communities
        )

        prompt = LOCAL_SEARCH_PROMPT.format(
            query=query,
            entities=entities_text or "(No relevant entities found)",
            relations=relations_text or "(No relevant relations found)",
            communities=communities_text or "(No relevant communities found)",
        )

        try:
            answer = await self.llm.complete([
                {"role": "user", "content": prompt},
            ], temperature=0.3, max_tokens=1024)

            return GraphRAGQueryResult(
                answer=answer.strip(),
                context_entities=[e.name for e in top_entities],
                context_communities=[c.title for c in relevant_communities],
                search_type="local",
            )
        except Exception as e:
            return GraphRAGQueryResult(answer=f"검색 중 오류 발생: {e}", search_type="local")

    async def global_search(self, index_id: str, query: str) -> GraphRAGQueryResult:
        """Community-level search: use all community summaries to answer broad questions."""
        idx = self._get_index(index_id)
        if not idx:
            return GraphRAGQueryResult(answer="인덱스를 찾을 수 없습니다.", search_type="global")

        # Use all community summaries
        summaries = "\n\n".join(
            f"### {c.title}\n{c.summary}" for c in idx.communities if c.summary
        )

        if not summaries:
            return GraphRAGQueryResult(answer="커뮤니티 요약이 없습니다.", search_type="global")

        prompt = GLOBAL_SEARCH_PROMPT.format(
            query=query,
            community_summaries=summaries,
        )

        try:
            answer = await self.llm.complete([
                {"role": "user", "content": prompt},
            ], temperature=0.5, max_tokens=1500)

            return GraphRAGQueryResult(
                answer=answer.strip(),
                context_communities=[c.title for c in idx.communities],
                search_type="global",
            )
        except Exception as e:
            return GraphRAGQueryResult(answer=f"검색 중 오류 발생: {e}", search_type="global")

    def get_context_for_simulation(self, index_id: str, topic: str) -> str:
        """Get a compact context string for injection into simulation agent prompts."""
        idx = self._get_index(index_id)
        if not idx or idx.status != GraphRAGStatus.READY:
            return ""

        # Build compact context from communities + key entities
        parts = []
        for c in idx.communities[:5]:
            if c.summary:
                parts.append(f"[{c.title}] {c.summary}")

        # Add top entities not covered by communities
        covered = set()
        for c in idx.communities[:5]:
            covered.update(c.entities)

        uncovered = [e for e in idx.entities if e.name not in covered][:10]
        if uncovered:
            entity_list = ", ".join(f"{e.name}({e.type})" for e in uncovered)
            parts.append(f"[기타 주요 개체] {entity_list}")

        return "\n".join(parts) if parts else ""

    # ── Persistence ──────────────────────────────────────────────────────

    def _save_index(self, idx: GraphRAGIndex):
        path = _DATA_DIR / f"{idx.id}.json"
        path.write_text(idx.model_dump_json(indent=2), encoding="utf-8")

    def _load_index(self, index_id: str) -> Optional[GraphRAGIndex]:
        path = _DATA_DIR / f"{index_id}.json"
        if not path.exists():
            return None
        try:
            return GraphRAGIndex.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _get_index(self, index_id: str) -> Optional[GraphRAGIndex]:
        if index_id in self._indices:
            return self._indices[index_id]
        idx = self._load_index(index_id)
        if idx:
            self._indices[index_id] = idx
        return idx

    def get_index_status(self, index_id: str) -> Optional[dict]:
        idx = self._get_index(index_id)
        if not idx:
            return None
        return {
            "id": idx.id,
            "status": idx.status.value,
            "entities": len(idx.entities),
            "relations": len(idx.relations),
            "communities": len(idx.communities),
            "error": idx.error,
        }

    def list_indices(self) -> list[dict]:
        results = []
        for path in _DATA_DIR.glob("*.json"):
            try:
                idx = GraphRAGIndex.model_validate_json(path.read_text(encoding="utf-8"))
                results.append({
                    "id": idx.id,
                    "ontology_id": idx.ontology_id,
                    "status": idx.status.value,
                    "entities": len(idx.entities),
                    "communities": len(idx.communities),
                })
            except Exception:
                continue
        return results

    def _parse_json(self, text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)
