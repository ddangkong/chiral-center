"""Database integration routes."""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional

from core.db_connector import parse_file
from core.db_indexer import db_indexer
from llm.factory import get_llm_client
from utils.logger import log

router = APIRouter()


class SearchRequest(BaseModel):
    project_id: str
    query: str
    top_k: int = 5
    threshold: float = 0.05


class ChatRequest(BaseModel):
    project_id: str
    messages: list[dict]  # [{"role": "user", "content": "..."}, ...]
    collection_name: str = ""
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str | None = None


@router.post("/upload")
async def upload_db_file(
    project_id: str = Form(...),
    file: UploadFile = File(...),
):
    """내부 DB 파일 업로드 및 인덱싱."""
    if not project_id:
        raise HTTPException(400, "project_id is required")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Empty file")

    chunks = parse_file(file.filename or "file", content)
    if not chunks:
        raise HTTPException(400, "No content could be extracted from the file")

    added = await db_indexer.add_file(
        project_id=project_id,
        file_name=file.filename or "unknown",
        chunks=chunks,
    )

    return {
        "project_id": project_id,
        "file_name": file.filename,
        "chunks_added": added,
        "total_records": db_indexer.record_count(project_id),
    }


@router.get("/status/{project_id}")
async def get_db_status(project_id: str):
    """프로젝트 DB 인덱스 상태 조회."""
    return {
        "project_id": project_id,
        "files": db_indexer.list_files(project_id),
        "total_records": db_indexer.record_count(project_id),
        "has_db": db_indexer.record_count(project_id) > 0,
    }


@router.post("/search")
async def search_db(req: SearchRequest):
    """쿼리와 유사한 DB 레코드 검색."""
    results = await db_indexer.search(
        project_id=req.project_id,
        query=req.query,
        top_k=req.top_k,
        threshold=req.threshold,
    )
    return {"results": results, "count": len(results)}


@router.post("/reembed/{project_id}")
async def reembed_db(project_id: str):
    """프로젝트 DB 레코드를 현재 임베딩 모델로 재임베딩."""
    count = await db_indexer.reembed_project(project_id)
    return {"project_id": project_id, "reembedded": count}


@router.delete("/clear/{project_id}")
async def clear_db(project_id: str):
    """프로젝트 DB 인덱스 초기화."""
    db_indexer.clear_project(project_id)
    return {"project_id": project_id, "cleared": True}


@router.post("/chat")
async def chat_with_db(req: ChatRequest):
    """DB 데이터 기반 LLM 채팅."""
    if not req.api_key:
        raise HTTPException(400, "LLM API 키가 필요합니다")

    if not req.messages:
        raise HTTPException(400, "메시지가 필요합니다")

    # 최근 사용자 메시지로 관련 데이터 검색
    last_user_msg = next(
        (m["content"] for m in reversed(req.messages) if m["role"] == "user"), ""
    )

    context_chunks = []
    if last_user_msg:
        keywords = [w for w in last_user_msg.split() if len(w) >= 2]

        # 1) 파일명 매칭 검색 (최우선 — 파일명에 키워드가 포함된 레코드)
        file_results = db_indexer.file_search(
            project_id=req.project_id,
            keywords=keywords,
            top_k=20,
        )

        # 2) 벡터 검색 (의미 유사도)
        vector_results = await db_indexer.search(
            project_id=req.project_id,
            query=last_user_msg,
            top_k=15,
            threshold=0.05,
        )

        # 3) 키워드 검색 (텍스트 + 파일명 매칭)
        keyword_results = db_indexer.keyword_search(
            project_id=req.project_id,
            keywords=keywords,
            top_k=10,
        )

        # 4) 병합 (파일명 매칭 우선, 중복 제거)
        seen_texts: set[str] = set()
        merged: list[dict] = []
        for r in file_results + keyword_results + vector_results:
            text_key = r["text"][:100]
            if text_key not in seen_texts:
                seen_texts.add(text_key)
                merged.append(r)

        context_chunks = merged[:25]
        log.info("db_chat_search", project=req.project_id, query=last_user_msg[:50],
                 file_match=len(file_results), vector=len(vector_results),
                 keyword=len(keyword_results), merged=len(context_chunks))

    # 파일 목록
    file_list = db_indexer.list_files(req.project_id)
    files_text = ", ".join(file_list) if file_list else "(없음)"

    # 컨텍스트에 파일명 태그 포함
    context_parts = []
    for r in context_chunks:
        context_parts.append(f"[출처: {r['file']}]\n{r['text']}")
    context_text = "\n---\n".join(context_parts) if context_parts else "(검색된 데이터 없음)"

    system_prompt = f"""당신은 '{req.collection_name or "DB"}' 데이터를 분석하는 전문 AI 어시스턴트입니다.

DB 파일 목록: {files_text}

아래는 사용자 질문과 관련된 DB 레코드입니다 ({len(context_chunks)}건).

[관련 데이터]
{context_text}

답변 형식 규칙 (반드시 준수):
1. **간결하게** 답변하세요. 장황하게 늘어뜨리지 마세요.
2. **표(table)** 형식을 적극 활용하세요. 비교, 목록, 수치가 있으면 반드시 마크다운 테이블로 정리하세요.
3. **핵심 → 근거** 순서로 답변하세요. 먼저 핵심 결론을 1~2줄로 말하고, 그 아래에 근거를 구조화하세요.
4. 각 정보의 **출처 파일명**을 괄호 안에 짧게 표기하세요. (예: (3월 10일 하이브 회의))
5. 원문을 그대로 베끼지 마세요. **요약·재구성**해서 전달하세요.
6. 데이터에 없는 내용은 "확인되지 않음"이라고 짧게 표기하세요.
7. 한국어로 답변하세요."""

    llm = get_llm_client(
        provider=req.provider,
        model=req.model,
        api_key=req.api_key,
        base_url=req.base_url,
        feature="db_chat",
    )

    messages = [{"role": "system", "content": system_prompt}] + req.messages

    try:
        response = await llm.complete(messages, temperature=0.2, max_tokens=2500)
    except Exception as e:
        log.error("db_chat_failed", error=str(e))
        raise HTTPException(500, f"채팅 실패: {str(e)}")

    return {
        "response": response,
        "context_count": len(context_chunks),
    }
