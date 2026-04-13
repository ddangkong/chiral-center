"""
persona_profiler.py — 수집된 데이터로 외부 인물 페르소나 자동 생성.

크롤링된 텍스트 청크를 분석해 의사결정 패턴, 말투, 가치관 등을
구조화된 프로필로 변환합니다.
"""

import json
from llm.base import BaseLLMClient
from core.db_indexer import db_indexer
from utils.logger import log


PROFILING_PROMPT = """다음은 {person_name}의 발언, 인터뷰, 기사에서 수집한 텍스트입니다.

=== 수집 데이터 (총 {chunk_count}건 중 주요 발췌) ===
{sample_texts}
=== 데이터 끝 ===

이 데이터를 분석해서 {person_name}의 페르소나 프로필을 생성하세요.

반드시 포함할 항목:
1. role: 직함/직책 (예: "Tesla/SpaceX CEO")
2. description: 이 인물의 배경과 영향력 (2-3문장)
3. personality: 성격 특성 (예: "도발적, 리스크 추구형, 직관적 의사결정")
4. decision_style: 의사결정 스타일 (예: "데이터보다 비전 우선, 빠른 판단, 실패 허용")
5. speech_style: 말투/커뮤니케이션 스타일 (예: "트위터 스타일 짧은 문장, 밈과 비유 활용, 도발적")
6. core_values: 핵심 가치관 3-5개 (예: ["기술 혁신", "인류 멀티플래닛", "제1원리 사고"])
7. known_stances: 주요 주제별 입장 (dict, 예: {{"AI": "위험하지만 필수", "전기차": "전면 전환 불가피"}})
8. blind_spots: 약점/편향 2-3개 (예: ["노동 이슈 경시", "과도한 낙관주의"])
9. stance: 이 인물이 조직 전략 회의에 참여한다면 취할 포지션
10. goals: 이 인물이 추구할 목표 3-4개
11. knowledge: 전문 분야 3-5개

JSON으로만 응답:
{{
  "role": "...",
  "description": "...",
  "personality": "...",
  "decision_style": "...",
  "speech_style": "...",
  "core_values": ["...", "..."],
  "known_stances": {{"주제": "입장", ...}},
  "blind_spots": ["...", "..."],
  "stance": "...",
  "goals": ["...", "..."],
  "knowledge": ["...", "..."]
}}
"""


async def profile_person(
    person_name: str,
    chunks: list[dict],
    llm: BaseLLMClient,
    project_id: str | None = None,
    focus_fields: list[str] | None = None,
) -> dict:
    """수집된 텍스트 청크로 인물 프로파일링.

    Args:
        person_name: 인물 이름 (예: "일론 머스크")
        chunks: 크롤러에서 수집한 텍스트 청크 리스트
        llm: LLM 클라이언트
        project_id: DB 인덱서에 저장할 프로젝트 ID (선택)

    Returns:
        프로파일링 결과 dict
    """
    if not chunks:
        raise ValueError("프로파일링할 데이터가 없습니다")

    log.info("profiling_start", person=person_name, chunks=len(chunks))

    # DB 인덱서에 저장 (시뮬레이션 시 RAG 검색용)
    if project_id:
        texts = [c["text"] for c in chunks]
        await db_indexer.add_file(
            project_id=project_id,
            file_name=f"crawl_{person_name}",
            chunks=texts,
        )
        log.info("profiling_indexed", person=person_name, project=project_id)

    # 프로파일링용 샘플 텍스트 선택 (LLM 컨텍스트 제한)
    sample_texts = _select_samples(chunks, max_chars=10000)

    prompt = PROFILING_PROMPT.format(
        person_name=person_name,
        chunk_count=len(chunks),
        sample_texts=sample_texts,
    )

    # 부족 필드 보강 지시 추가
    if focus_fields:
        field_labels = {
            "role": "직함/직책", "description": "배경/영향력", "personality": "성격 특성",
            "decision_style": "의사결정 스타일", "speech_style": "말투/커뮤니케이션",
            "core_values": "핵심 가치관", "known_stances": "주요 입장",
            "blind_spots": "약점/편향", "stance": "전략적 포지션",
            "goals": "추구 목표", "knowledge": "전문 분야",
        }
        focus_str = ", ".join(field_labels.get(f, f) for f in focus_fields)
        prompt += f"\n\n⚠️ 특히 다음 항목을 데이터에서 구체적 근거를 찾아 상세히 작성하세요: {focus_str}"

    response = await llm.complete([
        {"role": "system", "content": f"당신은 인물 분석 전문가입니다. {person_name}의 공개 발언과 기사를 분석해 정확한 페르소나 프로필을 생성합니다. 추측이 아닌 실제 데이터에 근거한 분석만 작성하세요. JSON으로만 응답하세요."},
        {"role": "user", "content": prompt},
    ], temperature=0.3, max_tokens=4000)

    profile = _parse_json(response)
    profile["name"] = person_name
    profile["source_count"] = len(chunks)
    profile["sources"] = list(set(c.get("source", "") for c in chunks))[:10]

    log.info("profiling_done", person=person_name, role=profile.get("role", ""))
    return profile


def _select_samples(chunks: list[dict], max_chars: int = 6000) -> str:
    """대표 샘플 텍스트 선택."""
    # Spread evenly across sources
    by_source: dict[str, list[dict]] = {}
    for c in chunks:
        src = c.get("source", "unknown")
        by_source.setdefault(src, []).append(c)

    selected = []
    total_chars = 0

    # Round-robin from each source
    source_lists = list(by_source.values())
    idx = 0
    while total_chars < max_chars and source_lists:
        for src_chunks in source_lists:
            if idx < len(src_chunks):
                text = src_chunks[idx]["text"]
                source = src_chunks[idx].get("source", "")
                entry = f"[{source}] {text}"
                if total_chars + len(entry) > max_chars:
                    continue
                selected.append(entry)
                total_chars += len(entry)
        idx += 1
        if idx >= max(len(s) for s in source_lists):
            break

    return "\n\n".join(selected)


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)
