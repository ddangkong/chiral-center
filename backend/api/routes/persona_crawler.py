"""외부 인물 크롤링 + 프로파일링 API.

SSE 비동기 모드: /auto-profile/start → 즉시 응답 + 백그라운드 태스크
                 /auto-profile/stream/{task_id} → SSE로 진행 상황 + 최종 결과
동기 모드:       /auto-profile → 기존 동기 방식 (로컬 dev용, Vercel timeout 초과 가능)
"""

import asyncio
import json as _json
import traceback
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.crawler import fetch_youtube_transcript, fetch_web_article, fetch_multiple_urls
from core.auto_search import auto_collect
from core.persona_profiler import profile_person
from llm.factory import get_llm_client
from utils.logger import log

router = APIRouter()

# 크롤링된 데이터 캐시: person_name -> chunks
_crawl_cache: dict[str, list[dict]] = {}

# 비동기 프로파일링 태스크 관리
_profile_tasks: dict[str, asyncio.Task] = {}
_profile_events: dict[str, list[dict]] = {}
_profile_results: dict[str, dict] = {}


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str | None = None


class CrawlRequest(BaseModel):
    person_name: str
    urls: list[str]  # YouTube URLs + 뉴스/웹 URLs 혼합 가능


class ProfileRequest(BaseModel):
    person_name: str
    llm: LLMConfig = LLMConfig()
    project_id: str | None = None  # DB 인덱싱용


class CrawlSingleRequest(BaseModel):
    url: str


@router.post("/crawl")
async def crawl_person(req: CrawlRequest):
    """여러 URL에서 인물 관련 데이터 수집."""
    if not req.urls:
        raise HTTPException(400, "URL을 하나 이상 입력하세요")

    try:
        chunks = await fetch_multiple_urls(req.urls)
    except Exception as e:
        log.error("crawl_failed", person=req.person_name, error=str(e))
        raise HTTPException(500, f"크롤링 실패: {str(e)}")

    if not chunks:
        raise HTTPException(400, "수집된 데이터가 없습니다. URL을 확인하세요.")

    # 캐시에 누적 저장
    existing = _crawl_cache.get(req.person_name, [])
    existing.extend(chunks)
    _crawl_cache[req.person_name] = existing

    return {
        "person_name": req.person_name,
        "new_chunks": len(chunks),
        "total_chunks": len(existing),
        "sources": list(set(c.get("source", "") for c in chunks)),
    }


@router.post("/crawl/youtube")
async def crawl_youtube(req: CrawlSingleRequest):
    """단일 YouTube 영상 자막 수집."""
    try:
        chunks = await fetch_youtube_transcript(req.url)
    except Exception as e:
        raise HTTPException(400, f"YouTube 자막 추출 실패: {str(e)}")

    return {
        "chunks": len(chunks),
        "preview": [c["text"][:100] for c in chunks[:3]],
        "source": chunks[0]["source"] if chunks else "",
    }


@router.post("/crawl/web")
async def crawl_web(req: CrawlSingleRequest):
    """단일 웹 페이지 본문 추출."""
    try:
        chunks = await fetch_web_article(req.url)
    except Exception as e:
        raise HTTPException(400, f"웹 크롤링 실패: {str(e)}")

    return {
        "chunks": len(chunks),
        "title": chunks[0].get("title", "") if chunks else "",
        "preview": [c["text"][:100] for c in chunks[:3]],
    }


@router.post("/profile")
async def profile_person_endpoint(req: ProfileRequest):
    """수집된 데이터로 인물 프로파일링."""
    chunks = _crawl_cache.get(req.person_name)
    if not chunks:
        raise HTTPException(404, f"'{req.person_name}'의 수집 데이터가 없습니다. 먼저 /crawl을 실행하세요.")

    if not req.llm.api_key:
        raise HTTPException(400, "LLM API 키가 필요합니다")

    llm = get_llm_client(
        provider=req.llm.provider,
        model=req.llm.model,
        api_key=req.llm.api_key,
        base_url=req.llm.base_url,
        feature="persona_profile",
    )

    try:
        profile = await profile_person(
            person_name=req.person_name,
            chunks=chunks,
            llm=llm,
            project_id=req.project_id,
        )
    except Exception as e:
        log.error("profiling_failed", person=req.person_name, error=str(e))
        raise HTTPException(500, f"프로파일링 실패: {str(e)}")

    return {
        "person_name": req.person_name,
        "profile": profile,
        "source_count": len(chunks),
    }


@router.get("/cache")
async def get_cache():
    """현재 캐시된 크롤링 데이터 목록."""
    return {
        name: {"chunks": len(chunks), "sources": list(set(c.get("source", "") for c in chunks))}
        for name, chunks in _crawl_cache.items()
    }


@router.delete("/cache/{person_name}")
async def clear_cache(person_name: str):
    """특정 인물의 캐시 삭제."""
    removed = _crawl_cache.pop(person_name, None)
    return {"cleared": person_name, "had_data": removed is not None}


# ── 자동 검색 + 크롤링 ──

class AutoSearchRequest(BaseModel):
    person_name: str
    sources: list[str] = ["web", "youtube"]  # "web", "youtube"
    date_from: Optional[str] = None  # "2024-01-01"
    date_to: Optional[str] = None
    llm: LLMConfig = LLMConfig()


@router.post("/auto-search")
async def auto_search_and_crawl(req: AutoSearchRequest):
    """인물 이름으로 자동 검색 + 크롤링.

    LLM으로 검색 키워드를 생성하고, 웹/유튜브에서 자동으로 수집합니다.
    """
    if not req.person_name.strip():
        raise HTTPException(400, "인물 이름을 입력하세요")

    # LLM으로 검색 키워드 생성
    keywords = ["인터뷰", "발언", "경영철학"]
    if req.llm.api_key:
        try:
            llm = get_llm_client(
                provider=req.llm.provider,
                model=req.llm.model,
                api_key=req.llm.api_key,
                base_url=req.llm.base_url,
                feature="persona_search",
            )
            kw_response = await llm.complete([
                {"role": "system", "content": "검색 키워드 생성 전문가. JSON 배열로만 응답."},
                {"role": "user", "content": f"""'{req.person_name}'에 대한 깊이 있는 검색을 위한 키워드를 10개 생성하세요.

요구사항:
- 이 인물의 소속 조직, 직함, 핵심 사업을 반드시 포함
- 인터뷰, 강연, 공식 발언을 찾을 수 있는 키워드 포함
- 의사결정 스타일, 경영철학, 리더십을 알 수 있는 키워드 포함
- 최근 뉴스/이슈/성과를 찾을 수 있는 키워드 포함
- 한국어 + 영어 키워드 혼합

예시 (일론 머스크의 경우):
["일론 머스크 SpaceX CEO 인터뷰", "Elon Musk Tesla 전략 발표", "일론 머스크 경영철학 리더십", "일론 머스크 최근 발언", "Elon Musk vision strategy", "일론 머스크 의사결정 스타일", "Tesla SpaceX 사업 전략", "일론 머스크 강연 연설", "Elon Musk interview leadership", "일론 머스크 기업 문화"]

JSON 배열로만 응답:"""},
            ], temperature=0.3, max_tokens=500)

            import json
            kw_text = kw_response.strip()
            if kw_text.startswith("```"):
                kw_text = "\n".join(kw_text.split("\n")[1:])
                if kw_text.endswith("```"):
                    kw_text = kw_text[:-3]
            keywords = json.loads(kw_text)
            log.info("keywords_generated", person=req.person_name, keywords=keywords)
        except Exception as e:
            log.warning("keyword_gen_failed", error=str(e))
            keywords = [
                f"{req.person_name} 인터뷰",
                f"{req.person_name} 경영철학",
                f"{req.person_name} 발언",
            ]

    try:
        result = await auto_collect(
            person_name=req.person_name,
            sources=req.sources,
            keywords=keywords,
            date_from=req.date_from,
            date_to=req.date_to,
        )
    except Exception as e:
        log.error("auto_search_failed", person=req.person_name, error=str(e))
        raise HTTPException(500, f"자동 검색 실패: {str(e)}")

    # 캐시에 저장
    chunks = result["crawled_chunks"]
    if chunks:
        existing = _crawl_cache.get(req.person_name, [])
        existing.extend(chunks)
        _crawl_cache[req.person_name] = existing

    return {
        "person_name": req.person_name,
        "keywords": keywords,
        "search_results": result["search_results"],
        "total_chunks": len(_crawl_cache.get(req.person_name, [])),
        "stats": result["stats"],
    }


# ── 적응형 프로파일링 (자동 반복 검색) ──

class AutoProfileRequest(BaseModel):
    person_name: str
    sources: list[str] = ["web", "youtube"]
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    llm: LLMConfig = LLMConfig()
    project_id: str | None = None
    max_iterations: int = 3


@router.post("/auto-profile")
async def auto_profile_person(req: AutoProfileRequest):
    """적응형 프로파일링: 필요한 정보가 모두 채워질 때까지 반복 검색.

    1. 초기 검색 + 크롤링 → 프로파일 생성
    2. 부족한 필드 분석
    3. 부족한 필드용 타겟 검색 → 추가 크롤링 → 프로파일 재생성
    4. 모든 필드 채워질 때까지 반복 (최대 max_iterations)
    """
    if not req.person_name.strip():
        raise HTTPException(400, "인물 이름을 입력하세요")
    if not req.llm.api_key:
        raise HTTPException(400, "LLM API 키가 필요합니다")

    llm = get_llm_client(
        provider=req.llm.provider,
        model=req.llm.model,
        api_key=req.llm.api_key,
        base_url=req.llm.base_url,
        feature="persona_profile",
    )

    # 초기 키워드 생성
    keywords = [f"{req.person_name} 인터뷰", f"{req.person_name} 발언"]
    try:
        kw_llm = get_llm_client(
            provider=req.llm.provider,
            model=req.llm.model,
            api_key=req.llm.api_key,
            base_url=req.llm.base_url,
            feature="persona_search",
        )
        kw_response = await kw_llm.complete([
            {"role": "system", "content": "검색 키워드 생성 전문가. JSON 배열로만 응답."},
            {"role": "user", "content": f"""'{req.person_name}'에 대한 깊이 있는 검색을 위한 키워드를 10개 생성하세요.

요구사항:
- 이 인물의 소속 조직, 직함, 핵심 사업을 반드시 포함
- 인터뷰, 강연, 공식 발언을 찾을 수 있는 키워드 포함
- 의사결정 스타일, 경영철학, 리더십을 알 수 있는 키워드 포함
- 최근 뉴스/이슈/성과를 찾을 수 있는 키워드 포함
- 한국어 + 영어 키워드 혼합

JSON 배열로만 응답:"""},
        ], temperature=0.3, max_tokens=500)

        import json as _json
        kw_text = kw_response.strip()
        if kw_text.startswith("```"):
            kw_text = "\n".join(kw_text.split("\n")[1:])
            if kw_text.endswith("```"):
                kw_text = kw_text[:-3]
        keywords = _json.loads(kw_text)
        log.info("auto_profile_keywords", person=req.person_name, keywords=keywords)
    except Exception as e:
        log.warning("auto_profile_kw_failed", error=str(e))
        keywords = [
            f"{req.person_name} 인터뷰",
            f"{req.person_name} 경영철학",
            f"{req.person_name} CEO 전략",
            f"{req.person_name} 발언 비전",
        ]

    from core.adaptive_profiler import adaptive_profile

    try:
        result = await adaptive_profile(
            person_name=req.person_name,
            sources=req.sources,
            llm=llm,
            initial_keywords=keywords,
            max_iterations=req.max_iterations,
            date_from=req.date_from,
            date_to=req.date_to,
            project_id=req.project_id,
            openai_api_key=req.llm.api_key if req.llm.provider == "openai" else None,
        )
    except Exception as e:
        log.error("auto_profile_failed", person=req.person_name, error=str(e))
        raise HTTPException(500, f"적응형 프로파일링 실패: {str(e)}")

    # 캐시에 저장 (기존 auto-search와 호환)
    chunks = result.get("crawled_chunks", [])
    if chunks:
        _crawl_cache[req.person_name] = chunks

    return {
        "person_name": req.person_name,
        "profile": result["profile"],
        "iterations": result["iterations"],
        "total_chunks": result["total_chunks"],
        "coverage": result["coverage"],
        "search_results": result.get("search_results", []),
    }


# ── 비동기 SSE 버전 (Vercel 30초 timeout 우회) ──

@router.post("/auto-profile/start")
async def auto_profile_start(req: AutoProfileRequest):
    """비동기 프로파일링 시작 — 즉시 task_id 반환, 결과는 SSE로."""
    if not req.person_name.strip():
        raise HTTPException(400, "인물 이름을 입력하세요")
    if not req.llm.api_key:
        raise HTTPException(400, "LLM API 키가 필요합니다")

    task_id = str(uuid.uuid4())
    _profile_events[task_id] = []

    async def _run():
        try:
            llm = get_llm_client(
                provider=req.llm.provider, model=req.llm.model,
                api_key=req.llm.api_key, base_url=req.llm.base_url,
                feature="persona_profile",
            )

            # 키워드 생성
            _profile_events[task_id].append({"type": "progress", "msg": "검색 키워드 생성 중..."})
            keywords = [f"{req.person_name} 인터뷰", f"{req.person_name} 발언"]
            try:
                kw_llm = get_llm_client(
                    provider=req.llm.provider, model=req.llm.model,
                    api_key=req.llm.api_key, base_url=req.llm.base_url,
                    feature="persona_search",
                )
                kw_response = await kw_llm.complete([
                    {"role": "system", "content": "검색 키워드 생성 전문가. JSON 배열로만 응답."},
                    {"role": "user", "content": f"'{req.person_name}'에 대한 깊이 있는 검색을 위한 키워드를 10개 생성하세요.\n한국어 + 영어 혼합. JSON 배열로만 응답:"},
                ], temperature=0.3, max_tokens=500)
                kw_text = kw_response.strip()
                if kw_text.startswith("```"):
                    kw_text = "\n".join(kw_text.split("\n")[1:])
                    if kw_text.endswith("```"):
                        kw_text = kw_text[:-3]
                keywords = _json.loads(kw_text)
                _profile_events[task_id].append({"type": "progress", "msg": f"키워드 {len(keywords)}개 생성 완료"})
            except Exception as e:
                log.warning("auto_profile_kw_failed", error=str(e))
                keywords = [f"{req.person_name} 인터뷰", f"{req.person_name} 경영철학", f"{req.person_name} CEO 전략"]
                _profile_events[task_id].append({"type": "progress", "msg": "기본 키워드 사용"})

            # 적응형 프로파일링
            _profile_events[task_id].append({"type": "progress", "msg": "검색 + 크롤링 시작..."})

            from core.adaptive_profiler import adaptive_profile

            def _on_progress(data: dict):
                _profile_events[task_id].append({"type": "progress", "msg": data.get("msg", ""), **data})

            result = await adaptive_profile(
                person_name=req.person_name,
                sources=req.sources,
                llm=llm,
                initial_keywords=keywords,
                max_iterations=req.max_iterations,
                date_from=req.date_from,
                date_to=req.date_to,
                project_id=req.project_id,
                openai_api_key=req.llm.api_key if req.llm.provider == "openai" else None,
                on_progress=_on_progress,
            )

            # 캐시
            chunks = result.get("crawled_chunks", [])
            if chunks:
                _crawl_cache[req.person_name] = chunks

            final = {
                "person_name": req.person_name,
                "profile": result["profile"],
                "iterations": result["iterations"],
                "total_chunks": result["total_chunks"],
                "coverage": result["coverage"],
                "search_results": result.get("search_results", []),
            }
            _profile_results[task_id] = final
            _profile_events[task_id].append({"type": "completed", "result": final})

        except Exception as exc:
            tb = traceback.format_exc()
            log.error("auto_profile_async_failed", person=req.person_name, error=str(exc))
            _profile_events[task_id].append({"type": "failed", "error": str(exc)[:300]})

    task = asyncio.create_task(_run())
    _profile_tasks[task_id] = task

    return {"task_id": task_id, "status": "started"}


@router.get("/auto-profile/stream/{task_id}")
async def auto_profile_stream(task_id: str):
    """SSE 스트림으로 프로파일링 진행 상황 + 결과 전송."""
    if task_id not in _profile_events:
        raise HTTPException(404, "Task not found")

    async def event_stream():
        cursor = 0
        for _ in range(600):  # max 10분
            events = _profile_events.get(task_id, [])
            while cursor < len(events):
                event = events[cursor]
                cursor += 1
                yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") in ("completed", "failed"):
                    # 정리
                    _profile_events.pop(task_id, None)
                    _profile_tasks.pop(task_id, None)
                    _profile_results.pop(task_id, None)
                    return
            await asyncio.sleep(0.5)
        yield f"data: {_json.dumps({'type': 'timeout'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ── 페르소나 채팅 ──

class ChatRequest(BaseModel):
    person_name: str
    profile: dict  # 프론트에서 전달하는 프로파일 데이터
    messages: list[dict]  # [{"role": "user", "content": "..."}, ...]
    llm: LLMConfig = LLMConfig()
    db_project_id: str | None = None  # DB 연동 시 프로젝트 ID


@router.post("/chat")
async def chat_with_persona(req: ChatRequest):
    """프로파일된 인물과 대화. DB 연동 시 관련 데이터를 컨텍스트로 제공."""
    if not req.llm.api_key:
        raise HTTPException(400, "LLM API 키가 필요합니다")

    profile = req.profile

    # DB 컨텍스트 검색 (연동된 경우)
    db_context = ""
    if req.db_project_id:
        from core.db_indexer import db_indexer
        last_user_msg = next(
            (m["content"] for m in reversed(req.messages) if m["role"] == "user"), ""
        )
        if last_user_msg:
            keywords = [w for w in last_user_msg.split() if len(w) >= 2]
            # 파일명 매칭 + 벡터 + 키워드 검색
            file_results = db_indexer.file_search(req.db_project_id, keywords, top_k=10)
            vector_results = await db_indexer.search(req.db_project_id, last_user_msg, top_k=10, threshold=0.05)
            keyword_results = db_indexer.keyword_search(req.db_project_id, keywords, top_k=5)
            # 병합
            seen: set[str] = set()
            merged = []
            for r in file_results + keyword_results + vector_results:
                key = r["text"][:100]
                if key not in seen:
                    seen.add(key)
                    merged.append(r)
            if merged[:15]:
                parts = [f"[{r['file']}] {r['text']}" for r in merged[:15]]
                db_context = "\n---\n".join(parts)
                log.info("persona_chat_db", person=req.person_name, db=req.db_project_id, chunks=len(merged[:15]))

    # 시스템 프롬프트
    db_section = ""
    if db_context:
        db_section = f"""

아래는 내부 DB에서 검색된 실제 데이터입니다. 이 인물의 관점에서 이 데이터를 참고하여 답변하세요.

[참고 데이터]
{db_context}
"""

    system_prompt = f"""당신은 {req.person_name}입니다. 다음 프로파일에 기반해서 이 인물로서 대화하세요.

직함: {profile.get('role', '')}
성격: {profile.get('personality', '')}
의사결정 스타일: {profile.get('decision_style', '')}
말투/커뮤니케이션: {profile.get('speech_style', '')}
핵심 가치관: {', '.join(profile.get('core_values', []))}
주요 입장: {profile.get('known_stances', {})}
약점/편향: {', '.join(profile.get('blind_spots', []))}
{db_section}
규칙:
- 반드시 {req.person_name}의 말투와 사고방식으로 답변하세요
- 이 인물이 실제로 할 법한 말을 하세요
- 단순히 짧게 답하지 말고, 이 인물의 경험과 관점에서 깊이 있는 분석과 의견을 제시하세요
- DB 데이터가 제공된 경우, 실제 데이터의 구체적 수치/사실을 인용하며 이 인물답게 해석하세요
- 필요하면 구조화된 답변(표, 번호 목록 등)을 사용하세요
- "저는 AI입니다" 같은 메타 발언을 하지 마세요
- 한국어로 답변하세요"""

    llm = get_llm_client(
        provider=req.llm.provider,
        model=req.llm.model,
        api_key=req.llm.api_key,
        base_url=req.llm.base_url,
        feature="persona_chat",
    )

    messages = [{"role": "system", "content": system_prompt}] + req.messages

    try:
        response = await llm.complete(messages, temperature=0.7, max_tokens=1500)
    except Exception as e:
        log.error("persona_chat_failed", person=req.person_name, error=str(e))
        raise HTTPException(500, f"대화 실패: {str(e)}")

    return {"response": response, "db_connected": bool(db_context)}
