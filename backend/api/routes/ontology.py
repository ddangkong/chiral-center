"""Ontology extraction routes."""
import pathlib
import asyncio
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from llm.factory import get_llm_client
from core.ontology_builder import OntologyBuilder
from core.graphiti_extractor import GraphitiExtractor
from core.graphiti_extractor import LLMConfig as GraphitiLLMConfig
from core.document_processor import doc_processor
from core.task_manager import task_manager
from core.session import get_session_id, register_owner, is_owner

router = APIRouter()

# In-memory store for ontology builders
_builders: dict[str, OntologyBuilder] = {}

_ONTO_DIR = pathlib.Path(__file__).parent.parent.parent / "data" / "ontologies"
_ONTO_DIR.mkdir(parents=True, exist_ok=True)


def _save_onto(result) -> None:
    (_ONTO_DIR / f"{result.id}.json").write_text(result.model_dump_json(), encoding="utf-8")


def _serialize_ontology_result(result) -> dict:
    return {
        "id": result.id,
        "topic": result.topic,
        "entity_types": [
            {"name": et.name, "description": et.description}
            for et in result.schema_def.entity_types
        ],
        "relation_types": [
            {"name": rt.name, "description": rt.description}
            for rt in result.schema_def.relation_types
        ],
        "entities": [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "description": e.description,
                "attributes": e.attributes,
            }
            for e in result.entities
        ],
        "relations": [
            {
                "id": r.id,
                "source_id": r.source_id,
                "target_id": r.target_id,
                "relation_type": r.relation_type,
                "weight": r.weight,
                "description": r.description,
            }
            for r in result.relations
        ],
    }


def _load_onto(ontology_id: str):
    """Load ontology from disk."""
    from models.ontology import OntologyResult
    path = _ONTO_DIR / f"{ontology_id}.json"
    if not path.exists():
        return None
    try:
        return OntologyResult.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


async def _load_onto_or_reconstruct(ontology_id: str):
    """Load ontology from disk, or reconstruct from graph data (disk + Neo4j)."""
    result = _load_onto(ontology_id)
    if result:
        return result

    from models.ontology import OntologyResult, OntologySchema, Entity, Relation
    from core.graph_builder import graph_builder

    graph = await graph_builder.get_graph_data(ontology_id)
    if not graph.get("nodes"):
        return None

    entities = []
    for n in graph["nodes"]:
        nid = n.get("id") or str(__import__('uuid').uuid4())
        nname = n.get("name") or n.get("label") or "Unknown"
        entities.append(Entity(
            id=nid,
            name=nname,
            type=n.get("type") or "Entity",
            description=n.get("description") or "",
            attributes=n.get("attributes") or {},
        ))
    relations = []
    for e in graph.get("edges", []):
        sid = e.get("source_id")
        tid = e.get("target_id")
        if not sid or not tid:
            continue
        relations.append(Relation(
            id=e.get("id") or str(__import__('uuid').uuid4()),
            source_id=sid,
            target_id=tid,
            relation_type=e.get("relation_type") or "RELATED_TO",
            weight=e.get("weight", 1.0),
            description=e.get("description") or "",
        ))

    result = OntologyResult(
        id=ontology_id,
        schema_def=OntologySchema(entity_types=[], relation_types=[]),
        entities=entities,
        relations=relations,
    )
    # Persist so this fallback only happens once
    _save_onto(result)
    return result


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: Optional[str] = None


class ExtractRequest(BaseModel):
    doc_ids: list[str] = []
    topic: str = ""
    purpose: str = ""
    llm: LLMConfig = LLMConfig()
    extract_entities: bool = True
    extract_relations: bool = True
    extract_events: bool = False
    extract_sentiment: bool = False


async def _build_extraction_llm(req: ExtractRequest, *, feature: str):
    return get_llm_client(
        provider=req.llm.provider,
        api_key=req.llm.api_key,
        model=req.llm.model,
        base_url=req.llm.base_url,
        feature=feature,
    )


async def _postprocess_extraction(result, *, store_builder=None) -> dict:
    if store_builder is not None:
        _builders[result.id] = store_builder
    _save_onto(result)

    try:
        from core.graph_builder import graph_builder
        await graph_builder.build_graph(result)
    except Exception:
        pass

    return _serialize_ontology_result(result)


async def _run_llm_extract_task(task_id: str, req: ExtractRequest, text: str, session_id: str) -> None:
    async def _progress(progress: int, message: str) -> None:
        task_manager.update_task(task_id, status="running", progress=progress, message=message)

    try:
        llm = await _build_extraction_llm(req, feature="ontology")
        builder = OntologyBuilder(llm)
        result = await builder.extract_ontology(
            text=text,
            topic=req.topic,
            purpose=req.purpose,
            extract_entities=req.extract_entities,
            extract_relations=req.extract_relations,
            progress_callback=_progress,
        )
        payload = await _postprocess_extraction(result, store_builder=builder)
        register_owner("ontology", result.id, session_id)
        task_manager.complete_task(
            task_id,
            message="온톨로지 추출이 완료되었습니다.",
            result=payload,
            meta={"ontology_id": result.id},
        )
    except Exception as exc:
        task_manager.fail_task(task_id, str(exc), message="온톨로지 추출 중 오류가 발생했습니다.")


async def _run_hybrid_extract_task(task_id: str, req: ExtractRequest, text: str, session_id: str) -> None:
    async def _progress(progress: int, message: str) -> None:
        task_manager.update_task(task_id, status="running", progress=progress, message=message)

    try:
        llm = await _build_extraction_llm(req, feature="kg_hybrid")
        from core.hybrid_extractor import HybridExtractor
        extractor = HybridExtractor(llm_client=llm)
        result = await extractor.extract(
            text=text,
            topic=req.topic or "",
            purpose=req.purpose or "",
            progress_callback=_progress,
        )
        payload = await _postprocess_extraction(result)
        register_owner("ontology", result.id, session_id)
        payload["method"] = "hybrid"
        payload["stats"] = result.attributes if hasattr(result, "attributes") else {}
        task_manager.complete_task(
            task_id,
            message="하이브리드 온톨로지 추출이 완료되었습니다.",
            result=payload,
            meta={"ontology_id": result.id, "method": "hybrid"},
        )
    except Exception as exc:
        task_manager.fail_task(task_id, str(exc), message="하이브리드 추출 중 오류가 발생했습니다.")


@router.post("/extract")
async def extract_ontology(req: ExtractRequest, request: Request):
    """Extract ontology from uploaded documents."""
    if not req.llm.api_key:
        raise HTTPException(400, "API key is required")

    # Get combined text from documents
    text = doc_processor.get_combined_text(req.doc_ids if req.doc_ids else None)
    if not text:
        raise HTTPException(400, "No document text available. Upload documents first.")

    # Create LLM client
    llm = get_llm_client(
        provider=req.llm.provider,
        api_key=req.llm.api_key,
        model=req.llm.model,
        base_url=req.llm.base_url,
        feature="ontology",
    )

    builder = OntologyBuilder(llm)
    result = await builder.extract_ontology(
        text=text,
        topic=req.topic,
        purpose=req.purpose,
        extract_entities=req.extract_entities,
        extract_relations=req.extract_relations,
    )

    _builders[result.id] = builder
    _save_onto(result)  # persist so graph build survives restart
    register_owner("ontology", result.id, get_session_id(request))

    # Also pre-build graph to disk so OntologyView works after server restart
    try:
        from core.graph_builder import graph_builder
        await graph_builder.build_graph(result)
    except Exception:
        pass  # non-fatal

    return _serialize_ontology_result(result)


@router.post("/extract/async")
async def extract_ontology_async(req: ExtractRequest, request: Request):
    """Start ontology extraction as a background task."""
    if not req.llm.api_key:
        raise HTTPException(400, "API key is required")

    text = doc_processor.get_combined_text(req.doc_ids if req.doc_ids else None)
    if not text:
        raise HTTPException(400, "No document text available. Upload documents first.")

    sid = get_session_id(request)
    task = task_manager.create_task(
        "ontology_extract",
        meta={
            "topic": req.topic,
            "purpose": req.purpose,
            "method": "llm",
            "doc_ids": req.doc_ids,
        },
    )
    task_manager.update_task(task.id, status="running", progress=2, message="문서를 불러오는 중...")
    asyncio.create_task(_run_llm_extract_task(task.id, req, text, sid))
    return {"task_id": task.id, "status": "running"}


@router.post("/extract/hybrid")
async def extract_hybrid(req: ExtractRequest, request: Request):
    """하이브리드 추출: KoNER(1차) + LLM(2차) — 비용 효율적."""
    if not req.llm.api_key:
        raise HTTPException(400, "API key is required")

    text = doc_processor.get_combined_text(req.doc_ids if req.doc_ids else None)
    if not text:
        raise HTTPException(400, "No document text available. Upload documents first.")

    llm = get_llm_client(
        provider=req.llm.provider,
        api_key=req.llm.api_key,
        model=req.llm.model,
        base_url=req.llm.base_url,
        feature="kg_hybrid",
    )

    from core.hybrid_extractor import HybridExtractor
    import logging
    _log = logging.getLogger(__name__)
    extractor = HybridExtractor(llm_client=llm)
    try:
        result = await extractor.extract(
            text=text,
            topic=req.topic or "",
            purpose=req.purpose or "",
        )
    except Exception as e:
        _log.error(f"[HYBRID] extraction failed: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(500, f"추출 실패: {type(e).__name__}: {str(e)[:200]}")

    _save_onto(result)
    register_owner("ontology", result.id, get_session_id(request))

    # Auto-build graph
    try:
        from core.graph_builder import graph_builder
        await graph_builder.build_graph(result)
    except Exception:
        pass

    payload = _serialize_ontology_result(result)
    payload["method"] = "hybrid"
    payload["stats"] = result.attributes if hasattr(result, "attributes") else {}
    return payload


@router.post("/extract/hybrid/async")
async def extract_hybrid_async(req: ExtractRequest, request: Request):
    """Start hybrid ontology extraction as a background task."""
    if not req.llm.api_key:
        raise HTTPException(400, "API key is required")

    text = doc_processor.get_combined_text(req.doc_ids if req.doc_ids else None)
    if not text:
        raise HTTPException(400, "No document text available. Upload documents first.")

    sid = get_session_id(request)
    task = task_manager.create_task(
        "ontology_extract",
        meta={
            "topic": req.topic,
            "purpose": req.purpose,
            "method": "hybrid",
            "doc_ids": req.doc_ids,
        },
    )
    task_manager.update_task(task.id, status="running", progress=2, message="문서를 불러오는 중...")
    asyncio.create_task(_run_hybrid_extract_task(task.id, req, text, sid))
    return {"task_id": task.id, "status": "running"}


@router.post("/extract/graphiti")
async def extract_ontology_graphiti(req: ExtractRequest, request: Request):
    """Graphiti(getzep) 기반 온톨로지 추출 — 기존 /extract보다 풍부한 관계 추출."""
    if not req.llm.api_key:
        raise HTTPException(400, "API key is required")

    text = doc_processor.get_combined_text(req.doc_ids if req.doc_ids else None)
    if not text:
        raise HTTPException(400, "No document text available. Upload documents first.")

    extractor = GraphitiExtractor(
        llm_cfg=GraphitiLLMConfig(
            provider=req.llm.provider,
            model=req.llm.model,
            api_key=req.llm.api_key,
            base_url=req.llm.base_url,
        )
    )

    try:
        result = await extractor.extract_ontology(
            text=text,
            topic=req.topic,
            purpose=req.purpose,
        )
    except Exception as exc:
        import traceback
        err_detail = traceback.format_exc()
        from utils.logger import log
        log.error("graphiti_extract_failed", error=str(exc), traceback=err_detail)
        raise HTTPException(500, f"Graphiti 추출 실패: {exc}") from exc
    finally:
        await extractor.close()

    _save_onto(result)
    register_owner("ontology", result.id, get_session_id(request))

    try:
        from core.graph_builder import graph_builder
        await graph_builder.build_graph(result)
    except Exception:
        pass

    return {
        "id": result.id,
        "topic": result.topic,
        "entity_types": [
            {"name": et.name, "description": et.description}
            for et in result.schema_def.entity_types
        ],
        "relation_types": [
            {"name": rt.name, "description": rt.description}
            for rt in result.schema_def.relation_types
        ],
        "entities": [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "description": e.description,
                "attributes": e.attributes,
            }
            for e in result.entities
        ],
        "relations": [
            {
                "id": r.id,
                "source_id": r.source_id,
                "target_id": r.target_id,
                "relation_type": r.relation_type,
                "weight": r.weight,
                "description": r.description,
            }
            for r in result.relations
        ],
    }


@router.get("/{ontology_id}")
async def get_ontology(ontology_id: str, request: Request):
    """Get ontology by ID."""
    if not is_owner("ontology", ontology_id, get_session_id(request)):
        raise HTTPException(404, "Ontology not found")

    for builder in _builders.values():
        result = builder.get_result(ontology_id)
        if result:
            return {
                "id": result.id,
                "topic": result.topic,
                "entities": len(result.entities),
                "relations": len(result.relations),
            }
    # Fallback: disk → graph reconstruction
    result = await _load_onto_or_reconstruct(ontology_id)
    if result:
        return {
            "id": result.id,
            "topic": result.topic,
            "entities": len(result.entities),
            "relations": len(result.relations),
        }
    raise HTTPException(404, "Ontology not found")
