"""Deep Research routes — OpenAI o3/o4-mini deep research API integration.

Also supports a third mode: `ddg-hybrid-research` which runs a custom
orchestrator (planner → dual-provider search (DDG + OpenAI web_search) →
normalize → dedupe → evaluator → synthesizer). See core/research/README.md.
"""
import asyncio
import datetime
import json
import pathlib
import traceback
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import AsyncOpenAI

from core.session import get_session_id, register_owner, is_owner, remove_owner
from core.research.orchestrator import run_orchestrated_research, OrchestratorResult

router = APIRouter()

# ── Orchestrator live task registry ──
# While a DDG-hybrid research is running we hold an asyncio.Task + a list of
# "progress events" that the SSE endpoint can tail. Once the task finishes
# and the session is persisted, the entry is dropped.
_orchestrator_tasks: dict[str, asyncio.Task] = {}
_orchestrator_events: dict[str, list[dict]] = {}


DDG_HYBRID_MODEL = "ddg-hybrid-research"

# ── 데이터 저장 (JSON 파일 기반) ──
_DATA_DIR = pathlib.Path(__file__).parent.parent.parent / "data" / "research"
_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _save_session(session: dict):
    path = _DATA_DIR / f"{session['id']}.json"
    path.write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")


def _load_session(session_id: str) -> Optional[dict]:
    path = _DATA_DIR / f"{session_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except:
        return None


def _list_sessions(session_id: str = "") -> list[dict]:
    sessions = []
    for f in sorted(_DATA_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            rid = data["id"]
            if session_id and not is_owner("research", rid, session_id):
                continue
            sessions.append({
                "id": rid,
                "title": data.get("title", ""),
                "status": data.get("status", ""),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "model": data.get("model", ""),
            })
        except:
            pass
    return sessions[:30]


# ── 시스템 프롬프트 ──
SYSTEM_PROMPT = """You are an elite research analyst who produces institutional-grade reports. You don't just answer questions — you decompose them into every dimension a decision-maker would need, then systematically research each one.

## CRITICAL: Query Decomposition Protocol

Before you begin searching, you MUST decompose the user's query into sub-topics:
1. Identify the query type (market analysis, company research, technology assessment, etc.)
2. Expand into all relevant dimensions
3. Research EVERY dimension

## Research Frameworks

### Market/Industry: Cover ALL of:
- Market Size & Growth (TAM, CAGR, projections)
- Market Segmentation (product type, price tier, channel, geography)
- Competitive Landscape (ALL major players with market share %)
- Per-Competitor Deep Dive (top 5-10: portfolio, pricing, distribution, performance)
- Consumer Analysis (demographics, preferences, buying behavior)
- Distribution & Supply Chain
- Pricing Analysis
- Regulatory Environment
- Trends & Disruptions
- Opportunities & Threats

### Company: Cover ALL of:
- Overview, Financials, Products, Market Position, Strategy, Leadership, Operations, Recent News, SWOT

## Search Strategy
- Minimum 15-20 searches per query
- Vary search terms, multi-language, source diversity
- Include specific numbers, not vague terms

## Language
Respond in the same language as the user's query."""


# ── Request/Response 모델 ──
class ResearchRequest(BaseModel):
    query: str
    model: str = "o4-mini-deep-research"  # o3-deep-research | o4-mini-deep-research
    api_key: str = ""
    session_id: Optional[str] = None


class ResearchStartResponse(BaseModel):
    session_id: str
    response_id: str
    status: str


# ── 엔드포인트 ──

@router.get("/sessions")
async def list_research_sessions(request: Request):
    """저장된 리서치 세션 목록 (현재 쿠키 세션 소유분만)."""
    return _list_sessions(session_id=get_session_id(request))


@router.get("/sessions/{session_id}")
async def get_research_session(session_id: str, request: Request):
    """특정 리서치 세션 조회."""
    if not is_owner("research", session_id, get_session_id(request)):
        raise HTTPException(404, "Session not found")
    session = _load_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@router.post("/start")
async def start_research(req: ResearchRequest, request: Request):
    """딥 리서치 시작.

    - o3-deep-research / o4-mini-deep-research: OpenAI Responses API 단일 호출
      (기존 동작)
    - ddg-hybrid-research: 자체 orchestrator (planner + DDG + openai_web +
      evaluator + synthesizer) 백그라운드 태스크 실행
    """
    if not req.api_key:
        raise HTTPException(400, "OpenAI API key is required")
    if not req.query.strip():
        raise HTTPException(400, "Query is required")

    client = AsyncOpenAI(api_key=req.api_key)

    session_id = req.session_id or str(uuid.uuid4())
    cookie_sid = get_session_id(request)
    if req.session_id:
        if not is_owner("research", req.session_id, cookie_sid):
            raise HTTPException(404, "Session not found")

    # ── DDG Hybrid mode ───────────────────────────────────────────
    if req.model == DDG_HYBRID_MODEL:
        now = datetime.datetime.now().isoformat()
        session = {
            "id": session_id,
            "title": req.query[:80],
            "query": req.query,
            "model": DDG_HYBRID_MODEL,
            "response_id": f"orchestrator:{session_id}",
            "status": "queued",
            "content": "",
            "sources": [],
            "search_steps": [],
            "plan": None,
            "evaluator_results": {},
            "created_at": now,
            "updated_at": now,
        }
        _save_session(session)
        register_owner("research", session_id, cookie_sid)

        # Launch orchestrator as a background task that updates both the
        # in-memory event log (for SSE tailing) and the session JSON file.
        _orchestrator_events[session_id] = []

        async def _progress(event_type: str, payload: dict) -> None:
            _orchestrator_events[session_id].append(
                {"type": event_type, **payload}
            )
            # Also bump status in the session file so list_sessions stays fresh
            s = _load_session(session_id)
            if s and event_type == "status":
                s["status"] = payload.get("status", s.get("status", ""))
                s["updated_at"] = datetime.datetime.now().isoformat()
                _save_session(s)

        async def _run() -> None:
            try:
                result: OrchestratorResult = await run_orchestrated_research(
                    client,
                    req.query,
                    progress_callback=_progress,
                )
                s = _load_session(session_id) or session
                patch = result.to_session_patch()
                s.update(patch)
                s["status"] = "completed"
                s["updated_at"] = datetime.datetime.now().isoformat()
                _save_session(s)
                _orchestrator_events[session_id].append(
                    {
                        "type": "completed",
                        "content": result.report,
                        "sources": result.sources,
                        "searchSteps": result.search_steps,
                    }
                )
            except Exception as exc:
                tb = traceback.format_exc()
                print(f"[RESEARCH] orchestrator crashed: {exc}\n{tb}", flush=True)
                s = _load_session(session_id) or session
                s["status"] = "failed"
                s["updated_at"] = datetime.datetime.now().isoformat()
                _save_session(s)
                _orchestrator_events[session_id].append(
                    {"type": "failed", "content": f"Orchestrator error: {str(exc)[:200]}"}
                )

        task = asyncio.create_task(_run())
        _orchestrator_tasks[session_id] = task

        return {
            "session_id": session_id,
            "response_id": f"orchestrator:{session_id}",
            "status": "queued",
        }

    # ── OpenAI o3/o4 mode (existing, unchanged) ──────────────────
    selected_model = (
        "o3-deep-research"
        if req.model == "o3-deep-research"
        else "o4-mini-deep-research"
    )

    try:
        response = await client.responses.create(
            model=selected_model,
            input=[
                {"role": "developer", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
                {"role": "user", "content": [{"type": "input_text", "text": req.query}]},
            ],
            tools=[{"type": "web_search_preview"}],
            reasoning={"summary": "detailed"},
            background=True,
        )

        session = {
            "id": session_id,
            "title": req.query[:80],
            "query": req.query,
            "model": selected_model,
            "response_id": response.id,
            "status": response.status,
            "content": "",
            "sources": [],
            "search_steps": [],
            "created_at": datetime.datetime.now().isoformat(),
            "updated_at": datetime.datetime.now().isoformat(),
        }
        _save_session(session)
        register_owner("research", session_id, cookie_sid)

        return {"session_id": session_id, "response_id": response.id, "status": response.status}

    except Exception as e:
        raise HTTPException(500, f"OpenAI API error: {str(e)}")


@router.get("/stream/{response_id}")
async def stream_research(response_id: str, api_key: str, request: Request):
    """리서치 진행 상황 SSE 스트리밍 (폴링 방식)."""
    if not api_key:
        raise HTTPException(400, "API key required")


    # 세션 찾기
    session = None
    for f in _DATA_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("response_id") == response_id:
                session = data
                break
        except:
            pass

    if not session or not is_owner("research", session.get("id", ""), get_session_id(request)):
        raise HTTPException(404, "Session not found")

    client = AsyncOpenAI(api_key=api_key)

    async def event_stream():
        nonlocal session
        prev_step_count = 0
        prev_source_count = 0

        for attempt in range(600):  # max 10분
            try:
                result = await client.responses.retrieve(response_id)

                if result.status in ("in_progress", "queued"):
                    output = result.output or []

                    # 검색 단계 추출
                    steps = []
                    for item in output:
                        if getattr(item, 'type', '') == 'web_search_call':
                            action = getattr(item, 'action', None)
                            steps.append({
                                "action_type": getattr(action, 'type', 'search') if action else 'search',
                                "query": getattr(action, 'query', '') if action else '',
                                "status": getattr(item, 'status', 'in_progress'),
                            })

                    if len(steps) > prev_step_count:
                        new_steps = steps[prev_step_count:]
                        for step in new_steps:
                            yield f"data: {json.dumps({'type': 'search_step', 'step': step, 'totalSteps': len(steps)}, ensure_ascii=False)}\n\n"
                        prev_step_count = len(steps)

                    # 진행 중 소스 실시간 추출
                    # 1차: message annotation (deep research가 중간에 partial message를 줄 때)
                    # 2차: web_search_call 결과에 포함된 URL (search result items)
                    interim_sources = []
                    seen_interim = set()

                    for item in output:
                        item_type = getattr(item, 'type', '')
                        if item_type == 'message':
                            for block in (getattr(item, 'content', []) or []):
                                for ann in (getattr(block, 'annotations', []) or []):
                                    url = getattr(ann, 'url', '')
                                    if url and url not in seen_interim:
                                        seen_interim.add(url)
                                        interim_sources.append({
                                            "url": url,
                                            "title": getattr(ann, 'title', ''),
                                        })
                        elif item_type == 'web_search_call' and getattr(item, 'status', '') == 'completed':
                            # web_search_call이 완료됐으면 결과가 있을 수 있음
                            # Responses API 구조: output 리스트에서 web_search_call 다음에
                            # 같은 call_id를 참조하는 결과 아이템이 올 수 있음
                            pass

                    # 새로 발견된 소스만 전송
                    if len(interim_sources) > prev_source_count:
                        new_sources = interim_sources[prev_source_count:]
                        yield f"data: {json.dumps({'type': 'interim_sources', 'sources': new_sources, 'totalSources': len(interim_sources)}, ensure_ascii=False)}\n\n"
                        prev_source_count = len(interim_sources)

                    # 경과 시간 + 검색 카운트 같이 표시 → 프론트에서 "진행 중" 느낌 강화
                    elapsed = attempt  # 초 단위 (1초 sleep × attempt)
                    yield f"data: {json.dumps({'type': 'status', 'status': result.status, 'totalSteps': len(steps), 'totalSources': prev_source_count, 'elapsedSeconds': elapsed})}\n\n"

                elif result.status == "completed":
                    output = result.output or []
                    report_text = getattr(result, 'output_text', '') or ''

                    # 소스 추출
                    sources = []
                    seen_urls = set()
                    for item in output:
                        if getattr(item, 'type', '') == 'message':
                            content_list = getattr(item, 'content', [])
                            if content_list:
                                annotations = getattr(content_list[0], 'annotations', [])
                                for ann in annotations:
                                    url = getattr(ann, 'url', '')
                                    if url and url not in seen_urls:
                                        seen_urls.add(url)
                                        sources.append({
                                            "url": url,
                                            "title": getattr(ann, 'title', ''),
                                        })

                    # 검색 단계
                    search_steps = []
                    for item in output:
                        if getattr(item, 'type', '') == 'web_search_call':
                            action = getattr(item, 'action', None)
                            search_steps.append({
                                "action_type": getattr(action, 'type', 'search') if action else 'search',
                                "query": getattr(action, 'query', '') if action else '',
                                "status": "completed",
                            })

                    # 세션 업데이트
                    if session:
                        session["status"] = "completed"
                        session["content"] = report_text
                        session["sources"] = sources
                        session["search_steps"] = search_steps
                        session["updated_at"] = __import__("datetime").datetime.now().isoformat()
                        _save_session(session)

                    yield f"data: {json.dumps({'type': 'completed', 'content': report_text, 'sources': sources, 'searchSteps': search_steps}, ensure_ascii=False)}\n\n"
                    return

                elif result.status == "failed":
                    if session:
                        session["status"] = "failed"
                        _save_session(session)
                    yield f"data: {json.dumps({'type': 'failed', 'content': 'Research failed. Please try again.'})}\n\n"
                    return

            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

            await asyncio.sleep(1.0)

        yield f"data: {json.dumps({'type': 'timeout'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/stream/orchestrator/{session_id}")
async def stream_orchestrator(session_id: str, request: Request):
    """SSE stream for the DDG hybrid orchestrator.

    Tails the `_orchestrator_events` list for the given session, yielding
    each event as they're appended by the background task. Emits the same
    event types as the /stream/{response_id} endpoint so the frontend can
    reuse its SSE handler: status, search_step, completed, failed.
    """
    if not is_owner("research", session_id, get_session_id(request)):
        raise HTTPException(404, "Session not found")

    async def event_stream():
        cursor = 0
        # Cap total wait at ~10 min to match the o3/o4 stream.
        for _ in range(600):
            events = _orchestrator_events.get(session_id, [])
            while cursor < len(events):
                event = events[cursor]
                cursor += 1
                payload = json.dumps(event, ensure_ascii=False)
                yield f"data: {payload}\n\n"
                if event.get("type") in ("completed", "failed"):
                    # Final event sent — shut down the SSE stream
                    _orchestrator_events.pop(session_id, None)
                    _orchestrator_tasks.pop(session_id, None)
                    return
            await asyncio.sleep(0.5)

        yield f"data: {json.dumps({'type': 'timeout'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.delete("/sessions/{session_id}")
async def delete_research_session(session_id: str, request: Request):
    """리서치 세션 삭제."""
    if not is_owner("research", session_id, get_session_id(request)):
        raise HTTPException(404, "Session not found")
    path = _DATA_DIR / f"{session_id}.json"
    if path.exists():
        path.unlink()
    remove_owner("research", session_id)
    return {"status": "deleted"}
