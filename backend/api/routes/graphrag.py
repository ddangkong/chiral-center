"""GraphRAG indexing and query routes — DB 컬렉션 기반."""
import json
import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from llm.factory import get_llm_client
from core.graphrag_engine import GraphRAGEngine
from core.db_indexer import db_indexer

router = APIRouter()

_engines: dict[str, GraphRAGEngine] = {}
# Map collection_id → graphrag index_id
_collection_index_map: dict[str, str] = {}


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    base_url: Optional[str] = None


class IndexRequest(BaseModel):
    collection_id: str
    llm: LLMConfig = LLMConfig()


class QueryRequest(BaseModel):
    index_id: str
    query: str
    search_type: str = "local"
    llm: LLMConfig = LLMConfig()


def _get_engine(llm_cfg: LLMConfig) -> GraphRAGEngine:
    key = f"{llm_cfg.provider}:{llm_cfg.model}"
    if key not in _engines:
        llm = get_llm_client(
            provider=llm_cfg.provider,
            api_key=llm_cfg.api_key,
            model=llm_cfg.model,
            base_url=llm_cfg.base_url,
        )
        _engines[key] = GraphRAGEngine(llm)
    return _engines[key]


@router.post("/index")
async def index_collection(req: IndexRequest):
    """DB 컬렉션의 레코드를 GraphRAG로 인덱싱 (SSE 스트림)."""
    if not req.llm.api_key:
        raise HTTPException(400, "API key is required")

    if not req.collection_id:
        raise HTTPException(400, "collection_id is required")

    # DB 인덱서에서 해당 컬렉션의 텍스트 레코드 가져오기
    records = db_indexer._index.get(req.collection_id, [])
    if not records:
        raise HTTPException(400, "DB 컬렉션에 레코드가 없습니다. 먼저 파일을 업로드하세요.")

    text_chunks = [r.text for r in records if r.text.strip()]
    if not text_chunks:
        raise HTTPException(400, "유효한 텍스트 레코드가 없습니다.")

    engine = _get_engine(req.llm)

    async def progress_stream():
        progress_state = {"stage": "", "current": 0, "total": 0}

        async def on_progress(stage: str, current: int, total: int):
            progress_state["stage"] = stage
            progress_state["current"] = current
            progress_state["total"] = total

        task = asyncio.create_task(
            engine.index_documents(req.collection_id, text_chunks, on_progress)
        )

        last_msg = ""
        while not task.done():
            msg = json.dumps({
                "type": "progress",
                "stage": progress_state["stage"],
                "current": progress_state["current"],
                "total": progress_state["total"],
            }, ensure_ascii=False)
            if msg != last_msg:
                yield f"data: {msg}\n\n"
                last_msg = msg
            await asyncio.sleep(0.5)

        try:
            idx = task.result()
            _collection_index_map[req.collection_id] = idx.id
            yield f"data: {json.dumps({'type': 'complete', 'index_id': idx.id, 'entities': len(idx.entities), 'relations': len(idx.relations), 'communities': len(idx.communities)}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        progress_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/query")
async def query_graphrag(req: QueryRequest):
    """GraphRAG 인덱스에 질의."""
    if not req.llm.api_key:
        raise HTTPException(400, "API key is required")

    engine = _get_engine(req.llm)

    if req.search_type == "global":
        result = await engine.global_search(req.index_id, req.query)
    else:
        result = await engine.local_search(req.index_id, req.query)

    return {
        "answer": result.answer,
        "context_entities": result.context_entities,
        "context_communities": result.context_communities,
        "search_type": result.search_type,
    }


@router.get("/status/{index_id}")
async def get_index_status(index_id: str):
    """인덱싱 상태 조회."""
    for engine in _engines.values():
        status = engine.get_index_status(index_id)
        if status:
            return status

    # 디스크에서 로드 시도
    engine = GraphRAGEngine.__new__(GraphRAGEngine)
    engine._indices = {}
    engine.llm = None
    status = engine.get_index_status(index_id)
    if status:
        return status

    raise HTTPException(404, "Index not found")


@router.get("/by-collection/{collection_id}")
async def get_index_by_collection(collection_id: str):
    """DB 컬렉션에 연결된 GraphRAG 인덱스 조회."""
    index_id = _collection_index_map.get(collection_id)
    if index_id:
        return {"index_id": index_id, "collection_id": collection_id}

    # 디스크 검색
    import pathlib
    data_dir = pathlib.Path(__file__).parent.parent.parent / "data" / "graphrag"
    if data_dir.exists():
        for path in data_dir.glob("*.json"):
            try:
                from models.graphrag import GraphRAGIndex
                idx = GraphRAGIndex.model_validate_json(path.read_text(encoding="utf-8"))
                if idx.ontology_id == collection_id:
                    _collection_index_map[collection_id] = idx.id
                    return {"index_id": idx.id, "collection_id": collection_id}
            except Exception:
                continue

    return {"index_id": None, "collection_id": collection_id}


@router.get("/index/{index_id}/communities")
async def get_communities(index_id: str):
    """커뮤니티 상세 조회."""
    for engine in _engines.values():
        idx = engine._get_index(index_id)
        if idx:
            return {
                "communities": [
                    {
                        "id": c.id,
                        "title": c.title,
                        "summary": c.summary,
                        "entities": c.entities,
                        "weight": c.weight,
                    }
                    for c in idx.communities
                ]
            }

    raise HTTPException(404, "Index not found")


@router.get("/context/{index_id}")
async def get_simulation_context(index_id: str, topic: str = ""):
    """시뮬레이션 주입용 컨텍스트."""
    for engine in _engines.values():
        context = engine.get_context_for_simulation(index_id, topic)
        if context:
            return {"context": context, "index_id": index_id}

    return {"context": "", "index_id": index_id}
