"""Build and query knowledge graph.

Primary storage: in-memory cache + disk (data/graphs/).
Optional: also writes to Neo4j when available.
"""
import json
import pathlib
from typing import Optional
import inspect
from collections.abc import Awaitable, Callable

import networkx as nx

from db.neo4j_client import neo4j_client
from models.ontology import OntologyResult
from utils.logger import log

_GRAPH_DIR = pathlib.Path(__file__).parent.parent / "data" / "graphs"
_GRAPH_DIR.mkdir(parents=True, exist_ok=True)

# In-memory cache: ontology_id -> {"nodes": [...], "edges": [...], "communities": [...]}
_cache: dict[str, dict] = {}


def _persist(ontology_id: str, data: dict) -> None:
    path = _GRAPH_DIR / f"{ontology_id}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _load_disk(ontology_id: str) -> Optional[dict]:
    path = _GRAPH_DIR / f"{ontology_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


class GraphBuilder:
    """Converts ontology results into a queryable knowledge graph."""

    def __init__(self):
        self.client = neo4j_client

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

    def _detect_communities(self, data: dict) -> dict:
        """Detect communities using Louvain algorithm and attach to data."""
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

        # Skip detection for very small graphs
        if len(nodes) < 5:
            for node in nodes:
                node["community_id"] = 0
            node_ids = [n["id"] for n in nodes]
            member_names = [n.get("name", "") for n in nodes]
            data["communities"] = [
                {
                    "id": 0,
                    "node_ids": node_ids,
                    "size": len(nodes),
                    "member_names": member_names,
                    "summary": "",
                }
            ] if nodes else []
            return data

        # Build networkx graph
        G = nx.Graph()
        node_id_set = {n["id"] for n in nodes}
        for node in nodes:
            G.add_node(node["id"])

        for edge in edges:
            src = edge.get("source_id")
            tgt = edge.get("target_id")
            if src in node_id_set and tgt in node_id_set:
                w = edge.get("weight", 1.0)
                if w is None:
                    w = 1.0
                G.add_edge(src, tgt, weight=float(w))

        # Run Louvain community detection
        try:
            communities = nx.community.louvain_communities(
                G, weight="weight", resolution=1.0, seed=42
            )
        except Exception:
            # Fallback: all nodes in one community
            communities = [set(n["id"] for n in nodes)]

        # Build node_id -> community_id mapping
        node_community_map: dict[str, int] = {}
        for i, comm in enumerate(communities):
            for node_id in comm:
                node_community_map[node_id] = i

        # Assign community_id to each node
        node_name_map = {n["id"]: n.get("name", "") for n in nodes}
        for node in nodes:
            node["community_id"] = node_community_map.get(node["id"], 0)

        # Build communities list
        community_list = []
        for i, comm in enumerate(communities):
            comm_node_ids = list(comm)
            community_list.append({
                "id": i,
                "node_ids": comm_node_ids,
                "size": len(comm_node_ids),
                "member_names": [node_name_map.get(nid, "") for nid in comm_node_ids],
                "summary": "",
            })

        data["communities"] = community_list
        return data

    async def build_graph(
        self,
        ontology: OntologyResult,
        progress_callback: Callable[[int, str], Awaitable[None] | None] | None = None,
    ) -> dict:
        ontology_id = ontology.id
        entity_map = {e.id: e for e in ontology.entities}
        await self._report_progress(progress_callback, 10, "온톨로지에서 그래프 노드를 구성하는 중...")

        nodes = [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "description": e.description,
                "attributes": e.attributes,
                "labels": [e.type],
            }
            for e in ontology.entities
        ]

        edges = [
            {
                "id": r.id,
                "source_id": r.source_id,
                "target_id": r.target_id,
                "relation_type": r.relation_type,
                "weight": r.weight,
                "description": r.description,
                "source_name": entity_map[r.source_id].name if r.source_id in entity_map else "",
                "target_name": entity_map[r.target_id].name if r.target_id in entity_map else "",
            }
            for r in ontology.relations
        ]

        data = {"nodes": nodes, "edges": edges}
        await self._report_progress(progress_callback, 40, "그래프 엣지와 속성을 정리하는 중...")

        # Detect communities
        data = self._detect_communities(data)
        await self._report_progress(progress_callback, 65, "커뮤니티 구조를 계산하는 중...")

        _cache[ontology_id] = data
        _persist(ontology_id, data)
        await self._report_progress(progress_callback, 82, "그래프를 디스크 캐시에 저장하는 중...")

        log.info(
            "graph_built",
            ontology_id=ontology_id,
            nodes=len(nodes),
            edges=len(edges),
            communities=len(data.get("communities", [])),
        )

        # Optionally write to Neo4j — failures are non-fatal
        neo4j_ok = False
        try:
            await self._report_progress(progress_callback, 90, "Neo4j에 그래프를 동기화하는 중...")
            await self._write_neo4j(ontology_id, nodes, edges)
            neo4j_ok = True
            log.info("graph_neo4j_synced", ontology_id=ontology_id)
        except Exception as exc:
            log.info("neo4j_skip", reason=str(exc)[:120])

        return {
            "ontology_id": ontology_id,
            "nodes": len(nodes),
            "edges": len(edges),
            "communities": len(data.get("communities", [])),
            "status": "complete",
            "neo4j": neo4j_ok,
        }

    async def summarize_communities(
        self, ontology_id: str, llm_client
    ) -> list[dict]:
        """Summarize each community cluster using an LLM."""
        data = await self.get_graph_data(ontology_id)
        communities = data.get("communities", [])

        if not communities:
            return []

        # Build a lookup for node details
        node_map = {n["id"]: n for n in data.get("nodes", [])}

        for comm in communities:
            # Only summarize communities with 2+ members
            if comm.get("size", 0) < 2:
                comm["summary"] = ""
                continue

            # Gather member details
            members_info = []
            for nid in comm.get("node_ids", []):
                node = node_map.get(nid)
                if node:
                    members_info.append(
                        f"- {node.get('name', '')} (유형: {node.get('type', '')}) : {node.get('description', '')}"
                    )

            if not members_info:
                comm["summary"] = ""
                continue

            members_text = "\n".join(members_info)
            prompt = (
                "다음 엔티티 그룹의 공통 주제와 관계를 2-3문장으로 요약하세요.\n\n"
                f"엔티티 목록:\n{members_text}\n\n"
                "요약:"
            )

            try:
                response = await llm_client.chat(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=300,
                )
                summary = response.get("content", "").strip() if isinstance(response, dict) else str(response).strip()
                comm["summary"] = summary
            except Exception as exc:
                log.info("community_summary_failed", community_id=comm["id"], reason=str(exc)[:120])
                comm["summary"] = ""

        # Persist updated data with summaries
        data["communities"] = communities
        _cache[ontology_id] = data
        _persist(ontology_id, data)

        log.info("communities_summarized", ontology_id=ontology_id, count=len(communities))
        return communities

    async def get_graph_data(self, ontology_id: str) -> dict:
        # 1. In-memory
        if ontology_id in _cache:
            data = _cache[ontology_id]
        else:
            # 2. Disk
            data = _load_disk(ontology_id)
            if not data:
                # 3. Neo4j fallback
                try:
                    data = await self._read_neo4j(ontology_id)
                    if not data.get("nodes"):
                        data = None
                except Exception:
                    data = None

            if not data:
                return {"nodes": [], "edges": [], "communities": []}

        # Auto-detect communities for legacy graphs missing community data
        if data.get("nodes") and not data.get("communities"):
            data = self._detect_communities(data)
            _cache[ontology_id] = data
            _persist(ontology_id, data)
        else:
            _cache[ontology_id] = data

        return data

    async def search_graph(self, ontology_id: str, query: str, limit: int = 20) -> list[dict]:
        data = await self.get_graph_data(ontology_id)
        q = query.lower()
        results = [
            n for n in data["nodes"]
            if q in n.get("name", "").lower() or q in n.get("description", "").lower()
        ]
        return results[:limit]

    # ── Neo4j helpers ─────────────────────────────────────────────────────────

    async def _write_neo4j(self, ontology_id: str, nodes: list, edges: list) -> None:
        await self.client.execute(
            "MATCH (n {ontology_id: $oid}) DETACH DELETE n",
            {"oid": ontology_id},
        )
        for node in nodes:
            label = node["type"].replace(" ", "_").replace("-", "_") or "Entity"
            await self.client.execute(
                f"""MERGE (n:{label} {{entity_id: $eid}})
                SET n.name=$name, n.type=$type, n.description=$desc,
                    n.attributes=$attrs, n.ontology_id=$oid""",
                {
                    "eid": node["id"], "name": node["name"], "type": node["type"],
                    "desc": node["description"],
                    "attrs": json.dumps(node.get("attributes", {}), ensure_ascii=False),
                    "oid": ontology_id,
                },
            )
        for edge in edges:
            rel = edge["relation_type"].upper().replace(" ", "_").replace("-", "_") or "RELATED_TO"
            try:
                await self.client.execute(
                    f"""MATCH (a {{entity_id: $src}}), (b {{entity_id: $tgt}})
                    MERGE (a)-[r:{rel}]->(b)
                    SET r.relation_id=$rid, r.weight=$w, r.description=$desc, r.ontology_id=$oid""",
                    {
                        "src": edge["source_id"], "tgt": edge["target_id"],
                        "rid": edge["id"], "w": edge["weight"],
                        "desc": edge["description"], "oid": ontology_id,
                    },
                )
            except Exception:
                pass

    async def _read_neo4j(self, ontology_id: str) -> dict:
        node_recs = await self.client.execute(
            """MATCH (n) WHERE n.ontology_id=$oid
            RETURN n.entity_id as id, n.name as name, n.type as type,
                   n.description as description, n.attributes as attributes""",
            {"oid": ontology_id},
        )
        nodes = []
        for r in node_recs:
            attrs = r.get("attributes", "{}")
            if isinstance(attrs, str):
                try:
                    attrs = json.loads(attrs)
                except Exception:
                    attrs = {}
            nodes.append({
                "id": r["id"], "name": r["name"], "type": r["type"],
                "description": r.get("description", ""), "attributes": attrs,
                "labels": [r["type"]],
            })

        edge_recs = await self.client.execute(
            """MATCH (a)-[r]->(b) WHERE r.ontology_id=$oid
            RETURN r.relation_id as id, a.entity_id as source_id, b.entity_id as target_id,
                   type(r) as relation_type, r.weight as weight, r.description as description,
                   a.name as source_name, b.name as target_name""",
            {"oid": ontology_id},
        )
        edges = [
            {
                "id": r.get("id", ""), "source_id": r["source_id"], "target_id": r["target_id"],
                "relation_type": r["relation_type"], "weight": r.get("weight", 1.0),
                "description": r.get("description", ""),
                "source_name": r.get("source_name", ""), "target_name": r.get("target_name", ""),
            }
            for r in edge_recs
        ]
        return {"nodes": nodes, "edges": edges, "communities": []}


graph_builder = GraphBuilder()
