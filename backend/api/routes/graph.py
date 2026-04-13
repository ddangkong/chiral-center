"""Knowledge graph routes."""
import asyncio
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from llm.factory import get_llm_client
from core.graph_builder import graph_builder
from core.task_manager import task_manager
from core.session import get_session_id, is_owner


def _check_ontology_owner(ontology_id: str, request: Request) -> None:
    """그래프 리소스는 부모 온톨로지의 소유권을 그대로 따름."""
    if not is_owner("ontology", ontology_id, get_session_id(request)):
        raise HTTPException(404, "Ontology not found")

router = APIRouter()


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: Optional[str] = None


class BuildRequest(BaseModel):
    ontology_id: str
    llm: LLMConfig = LLMConfig()


async def _run_graph_build_task(task_id: str, ontology_result) -> None:
    async def _progress(progress: int, message: str) -> None:
        task_manager.update_task(task_id, status="running", progress=progress, message=message)

    try:
        result = await graph_builder.build_graph(ontology_result, progress_callback=_progress)
        task_manager.complete_task(
            task_id,
            message="그래프 빌드가 완료되었습니다.",
            result=result,
            meta={"ontology_id": ontology_result.id},
        )
    except Exception as exc:
        task_manager.fail_task(task_id, str(exc), message="그래프 빌드 중 오류가 발생했습니다.")


@router.post("/build")
async def build_graph(req: BuildRequest, request: Request):
    """Build knowledge graph from ontology."""
    _check_ontology_owner(req.ontology_id, request)
    # Find the ontology result — check memory then disk
    from api.routes.ontology import _builders, _load_onto_or_reconstruct

    ontology_result = None
    for builder in _builders.values():
        result = builder.get_result(req.ontology_id)
        if result:
            ontology_result = result
            break

    if not ontology_result:
        ontology_result = await _load_onto_or_reconstruct(req.ontology_id)

    if not ontology_result:
        raise HTTPException(404, "Ontology not found. Re-run extraction.")

    result = await graph_builder.build_graph(ontology_result)
    return result


@router.post("/build/async")
async def build_graph_async(req: BuildRequest, request: Request):
    """Build graph as a background task."""
    _check_ontology_owner(req.ontology_id, request)
    from api.routes.ontology import _builders, _load_onto_or_reconstruct

    ontology_result = None
    for builder in _builders.values():
        result = builder.get_result(req.ontology_id)
        if result:
            ontology_result = result
            break

    if not ontology_result:
        ontology_result = await _load_onto_or_reconstruct(req.ontology_id)

    if not ontology_result:
        raise HTTPException(404, "Ontology not found. Re-run extraction.")

    task = task_manager.create_task(
        "graph_build",
        meta={"ontology_id": req.ontology_id},
    )
    task_manager.update_task(task.id, status="running", progress=5, message="그래프 빌드를 준비하는 중...")
    asyncio.create_task(_run_graph_build_task(task.id, ontology_result))
    return {"task_id": task.id, "status": "running"}


@router.get("/nodes")
async def get_nodes(ontology_id: str, request: Request):
    """Get all nodes for an ontology."""
    _check_ontology_owner(ontology_id, request)
    data = await graph_builder.get_graph_data(ontology_id)
    return {"nodes": data["nodes"], "count": len(data["nodes"])}


@router.get("/edges")
async def get_edges(ontology_id: str, request: Request):
    """Get all edges for an ontology."""
    _check_ontology_owner(ontology_id, request)
    data = await graph_builder.get_graph_data(ontology_id)
    return {"edges": data["edges"], "count": len(data["edges"])}


@router.get("/data")
async def get_graph_data(ontology_id: str, request: Request):
    """Get full graph data (nodes + edges) for visualization."""
    _check_ontology_owner(ontology_id, request)
    data = await graph_builder.get_graph_data(ontology_id)
    return data


@router.get("/search")
async def search_graph(ontology_id: str, q: str, request: Request, limit: int = 20):
    """Search nodes in the graph."""
    _check_ontology_owner(ontology_id, request)
    results = await graph_builder.search_graph(ontology_id, q, limit)
    return {"results": results, "count": len(results)}


# ── Community endpoints ──

@router.get("/communities")
async def get_communities(ontology_id: str, request: Request):
    """Get detected communities for a graph."""
    _check_ontology_owner(ontology_id, request)
    data = await graph_builder.get_graph_data(ontology_id)
    communities = data.get("communities", [])
    return {"communities": communities, "count": len(communities)}


class SummarizeRequest(BaseModel):
    ontology_id: str
    llm: LLMConfig = LLMConfig()


@router.post("/communities/summarize")
async def summarize_communities(req: SummarizeRequest, request: Request):
    """LLM으로 각 커뮤니티 요약 생성."""
    _check_ontology_owner(req.ontology_id, request)
    if not req.llm.api_key:
        raise HTTPException(400, "API key is required")

    llm = get_llm_client(
        provider=req.llm.provider,
        api_key=req.llm.api_key,
        model=req.llm.model,
        base_url=req.llm.base_url,
        feature="community_summary",
    )

    communities = await graph_builder.summarize_communities(req.ontology_id, llm)
    return {"communities": communities, "count": len(communities)}
