"""Document upload and management routes."""
import re

import httpx
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from core.document_processor import doc_processor

router = APIRouter()

import os
RESEARCH_APP_URL = os.environ.get("RESEARCH_APP_URL", "http://localhost:3000")


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload and process a document."""
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:  # 50MB limit
        raise HTTPException(413, "File too large (max 50MB)")

    doc = await doc_processor.process_file(file.filename, content)

    return {
        "id": doc.id,
        "filename": doc.filename,
        "ext": doc.ext,
        "size": doc.size,
        "pages": doc.pages,
        "status": doc.status.value,
        "chunks": len(doc.chunks),
    }


# ── Research import (proxy to deep-research-app) ──────────────


@router.get("/research/sessions")
async def list_research_sessions():
    """deep-research-app 대화 목록을 프록시로 반환."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{RESEARCH_APP_URL}/api/conversations")
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(503, "deep-research-app이 실행 중이 아닙니다 (localhost:3000)")
    except Exception as e:
        raise HTTPException(502, f"리서치 세션 조회 실패: {e}")


class ResearchImportRequest(BaseModel):
    conversation_id: str
    conversation_title: str = ""


@router.post("/research/import")
async def import_research(req: ResearchImportRequest):
    """빌트인 리서치 세션을 가상 문서로 변환."""
    import json as _json
    import pathlib

    # 빌트인 리서치 데이터에서 로드
    research_dir = pathlib.Path(__file__).parent.parent.parent / "data" / "research"
    session_file = research_dir / f"{req.conversation_id}.json"

    data = None
    if session_file.exists():
        try:
            data = _json.loads(session_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 빌트인에 없으면 deep-research-app 프록시 시도 (레거시 호환)
    if not data:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{RESEARCH_APP_URL}/api/conversations/{req.conversation_id}"
                )
                resp.raise_for_status()
                conv_data = resp.json()
                messages = conv_data.get("messages", [])
                assistant_msgs = [
                    m for m in messages
                    if m.get("role") == "assistant" and m.get("status") == "completed"
                ]
                if assistant_msgs:
                    msg = assistant_msgs[-1]
                    data = {
                        "content": msg.get("content", ""),
                        "sources": msg.get("sources", []),
                        "title": conv_data.get("title", ""),
                    }
        except Exception:
            pass

    if not data or not data.get("content"):
        raise HTTPException(404, "완료된 리서치 보고서가 없습니다")

    report_text = data.get("content", "")
    sources = data.get("sources", [])

    # 소스 부록 조합
    source_lines = []
    for i, s in enumerate(sources, 1):
        line = f"[{i}] {s.get('title', 'Untitled')}\n    URL: {s.get('url', '')}"
        snippet = s.get("snippet", "")
        if snippet:
            line += f"\n    Snippet: {snippet[:200]}"
        source_lines.append(line)

    full_text = report_text
    if source_lines:
        full_text += "\n\n---\n\n## Sources\n\n" + "\n\n".join(source_lines)

    # 파일명 생성
    title = req.conversation_title or data.get("title", "research")
    slug = re.sub(r"[^\w가-힣]+", "_", title)[:40].strip("_")
    filename = f"research_{slug}.md"

    doc = doc_processor.add_virtual_document(full_text, filename=filename, source="deep-research")

    return {
        "id": doc.id,
        "filename": doc.filename,
        "ext": doc.ext,
        "size": doc.size,
        "pages": doc.pages,
        "status": doc.status.value,
        "chunks": len(doc.chunks),
    }


class SyncKeyRequest(BaseModel):
    api_key: str


@router.post("/research/sync-key")
async def sync_research_api_key(req: SyncKeyRequest):
    """chiral_new의 OpenAI API 키를 deep-research-app에 동기화."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{RESEARCH_APP_URL}/api/settings",
                json={"apiKey": req.api_key},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(503, "deep-research-app이 실행 중이 아닙니다 (localhost:3000)")
    except Exception as e:
        raise HTTPException(502, f"API 키 동기화 실패: {e}")


# ── Document CRUD ─────────────────────────────────────────────


@router.get("/{doc_id}")
async def get_document(doc_id: str):
    """Get document details."""
    doc = doc_processor.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    return {
        "id": doc.id,
        "filename": doc.filename,
        "ext": doc.ext,
        "size": doc.size,
        "pages": doc.pages,
        "status": doc.status.value,
        "chunks": len(doc.chunks),
        "text_preview": doc.extracted_text[:500] if doc.extracted_text else "",
    }


@router.get("/")
async def list_documents():
    """List all uploaded documents."""
    docs = doc_processor.get_all_documents()
    return {
        "count": len(docs),
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "ext": d.ext,
                "size": d.size,
                "status": d.status.value,
                "chunks": len(d.chunks),
            }
            for d in docs
        ],
    }
