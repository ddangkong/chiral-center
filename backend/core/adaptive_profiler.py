"""
adaptive_profiler.py — 적응형 크롤링 + 프로파일링.

필요한 페르소나 필드가 모두 채워질 때까지 반복적으로 검색·크롤링합니다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.auto_search import auto_collect
from core.persona_profiler import profile_person
from llm.base import BaseLLMClient
from utils.logger import log

PERSONA_FIELDS = [
    "role", "description", "personality", "decision_style",
    "speech_style", "core_values", "known_stances",
    "blind_spots", "stance", "goals", "knowledge",
]

# 필드별 부족할 때 검색에 사용할 전략 키워드
FIELD_SEARCH_STRATEGIES: dict[str, list[str]] = {
    "role": ["직함 직책", "CEO founder 대표", "title position career"],
    "description": ["프로필 경력 이력", "biography background", "약력 소개"],
    "personality": ["성격 리더십 스타일", "personality leadership style", "인물 평가"],
    "decision_style": ["의사결정 방식 경영", "decision making process", "전략 회의 운영"],
    "speech_style": ["인터뷰 발언 연설", "speech style communication", "강연 대담"],
    "core_values": ["가치관 철학 신념", "philosophy principles values", "경영 철학"],
    "known_stances": ["입장 견해 주장", "opinion stance statement", "발언 논평"],
    "blind_spots": ["비판 논란 약점", "criticism controversy weakness", "실패 문제점"],
    "stance": ["전략 비전 방향성", "strategy vision direction", "포지션 역할"],
    "goals": ["목표 계획 로드맵", "goal plan roadmap future", "향후 계획"],
    "knowledge": ["전문 분야 기술", "expertise specialization domain", "전문성 역량"],
}

COVERAGE_ANALYSIS_PROMPT = """다음은 '{person_name}'의 페르소나 프로필입니다. 각 필드의 품질을 평가하세요.

{profile_json}

각 필드에 대해:
- 실제 근거 있는 구체적 내용이면 "good" (0.7~1.0)
- 일반적이고 누구에게나 적용될 수 있는 내용이면 "weak" (0.3~0.6)
- 비어있거나 의미없으면 "missing" (0.0~0.2)

특히 다음을 엄격히 평가:
- role: 실제 소속·직함이 구체적으로 명시되어 있는가?
- known_stances: 실제 발언/입장이 인용되어 있는가, 추측인가?
- blind_spots: 구체적 비판/논란이 언급되어 있는가?
- speech_style: 실제 발언 패턴에 기반한 분석인가?

JSON으로만 응답:
{{
  "field_scores": {{
    "role": {{"score": 0.9, "reason": "구체적 직함 명시"}},
    "description": {{"score": 0.7, "reason": "..."}},
    ...모든 11개 필드...
  }},
  "overall_coverage": 0.75,
  "critical_gaps": ["blind_spots", "speech_style"]
}}
"""

GAP_QUERY_PROMPT = """'{person_name}'의 페르소나 프로필에서 다음 정보가 부족합니다:

부족한 필드:
{missing_fields_desc}

이미 수집한 소스:
{existing_sources}

이 부족한 정보를 채우기 위한 검색 키워드를 8개 생성하세요.
각 키워드는 부족한 필드를 직접 채울 수 있는 구체적인 내용을 찾을 수 있어야 합니다.

예시:
- blind_spots가 부족하면: "{person_name} 논란", "{person_name} criticism failure"
- speech_style이 부족하면: "{person_name} 인터뷰 전문", "{person_name} 강연 영상"
- decision_style이 부족하면: "{person_name} 의사결정 사례", "{person_name} management style"

JSON 배열로만 응답:
"""


@dataclass
class ProfileCoverage:
    """페르소나 필드 커버리지 추적."""
    field_scores: dict[str, float] = field(default_factory=dict)
    field_reasons: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    weak: list[str] = field(default_factory=list)
    iteration: int = 0

    @property
    def coverage_ratio(self) -> float:
        if not self.field_scores:
            return 0.0
        return sum(self.field_scores.values()) / len(PERSONA_FIELDS)

    @property
    def is_complete(self) -> bool:
        """모든 필드가 0.5 이상이면 완료."""
        return all(
            self.field_scores.get(f, 0) >= 0.5
            for f in PERSONA_FIELDS
        )

    @property
    def needs_work(self) -> list[str]:
        """0.5 미만인 필드 목록."""
        return [
            f for f in PERSONA_FIELDS
            if self.field_scores.get(f, 0) < 0.5
        ]


async def adaptive_profile(
    person_name: str,
    sources: list[str],
    llm: BaseLLMClient,
    initial_keywords: list[str],
    max_iterations: int = 3,
    date_from: str | None = None,
    date_to: str | None = None,
    project_id: str | None = None,
    on_progress: Callable[[dict], None] | None = None,
    openai_api_key: str | None = None,
) -> dict:
    """적응형 프로파일링 메인 루프.

    1. 초기 검색 + 크롤링
    2. 프로파일 생성 → 커버리지 분석
    3. 부족한 필드용 타겟 검색 → 추가 크롤링
    4. 모든 필드 채워질 때까지 반복 (최대 max_iterations)
    """
    all_chunks: list[dict] = []
    all_search_results: list[dict] = []
    visited_urls: set[str] = set()
    iteration_history: list[dict] = []
    profile: dict = {}

    def _notify(data: dict):
        if on_progress:
            try:
                on_progress(data)
            except Exception:
                pass

    # ── Iteration 0: 초기 광범위 검색 ──
    _notify({"iteration": 0, "phase": "searching", "msg": "초기 검색 중..."})
    log.info("adaptive_start", person=person_name, max_iter=max_iterations)

    result = await auto_collect(
        person_name=person_name,
        sources=sources,
        keywords=initial_keywords,
        date_from=date_from,
        date_to=date_to,
        max_web=15,
        max_youtube=8,
        exclude_urls=visited_urls,
        openai_api_key=openai_api_key,
    )
    _collect_urls(result, visited_urls)
    all_chunks.extend(result.get("crawled_chunks", []))
    all_search_results.extend(result.get("search_results", []))

    _notify({
        "iteration": 0, "phase": "profiling",
        "msg": f"초기 데이터 {len(all_chunks)}건 수집 완료, 프로파일 생성 중...",
    })

    if not all_chunks:
        log.warning("adaptive_no_chunks", person=person_name)
        return {
            "profile": {},
            "iterations": [],
            "total_chunks": 0,
            "coverage": 0.0,
        }

    # 첫 프로파일 생성
    profile = await profile_person(
        person_name=person_name,
        chunks=all_chunks,
        llm=llm,
        project_id=project_id,
    )

    # 커버리지 분석
    coverage = await analyze_coverage(person_name, profile, llm)
    iteration_history.append({
        "iteration": 0,
        "coverage": coverage.coverage_ratio,
        "missing": coverage.needs_work,
        "chunks": len(all_chunks),
        "phase": "initial",
    })

    _notify({
        "iteration": 0, "phase": "analyzed",
        "coverage": coverage.coverage_ratio,
        "missing": coverage.needs_work,
        "msg": f"커버리지 {coverage.coverage_ratio:.0%}, 부족: {', '.join(coverage.needs_work) or '없음'}",
    })

    log.info(
        "adaptive_iter_done",
        iteration=0,
        coverage=f"{coverage.coverage_ratio:.2f}",
        missing=coverage.needs_work,
        chunks=len(all_chunks),
    )

    # ── 반복 탐색 ──
    for i in range(1, max_iterations + 1):
        if coverage.is_complete:
            log.info("adaptive_complete", iteration=i - 1, person=person_name)
            break

        gaps = coverage.needs_work
        _notify({
            "iteration": i, "phase": "gap_search",
            "msg": f"[{i}/{max_iterations}] 부족 필드 보충 검색: {', '.join(gaps)}",
        })

        # 부족 필드용 타겟 검색어 생성
        gap_queries = await generate_gap_queries(
            person_name, gaps, list(visited_urls)[:20], llm,
        )
        log.info("adaptive_gap_queries", iteration=i, queries=gap_queries)

        # 타겟 검색 + 크롤링 (작은 범위)
        result = await auto_collect(
            person_name=person_name,
            sources=sources,
            keywords=gap_queries,
            date_from=date_from,
            date_to=date_to,
            max_web=10,
            max_youtube=5,
            exclude_urls=visited_urls,
            openai_api_key=openai_api_key,
        )
        _collect_urls(result, visited_urls)
        new_chunks = result.get("crawled_chunks", [])
        all_chunks.extend(new_chunks)
        all_search_results.extend(result.get("search_results", []))

        if not new_chunks:
            log.info("adaptive_no_new_chunks", iteration=i)
            iteration_history.append({
                "iteration": i, "coverage": coverage.coverage_ratio,
                "missing": gaps, "chunks": 0, "phase": "no_new_data",
            })
            # 새 데이터 없으면 더 시도해봐야 의미 없음
            break

        _notify({
            "iteration": i, "phase": "re_profiling",
            "msg": f"추가 데이터 {len(new_chunks)}건, 프로파일 재생성 중...",
        })

        # 전체 데이터로 재프로파일 (focus_fields 지정)
        new_profile = await profile_person(
            person_name=person_name,
            chunks=all_chunks,
            llm=llm,
            project_id=project_id,
            focus_fields=gaps,
        )

        # 프로파일 병합 (강한 필드 보존)
        profile = merge_profiles(profile, new_profile, coverage)

        # 재분석
        coverage = await analyze_coverage(person_name, profile, llm)
        iteration_history.append({
            "iteration": i,
            "coverage": coverage.coverage_ratio,
            "missing": coverage.needs_work,
            "chunks": len(new_chunks),
            "phase": "gap_filled",
        })

        _notify({
            "iteration": i, "phase": "analyzed",
            "coverage": coverage.coverage_ratio,
            "missing": coverage.needs_work,
            "msg": f"커버리지 {coverage.coverage_ratio:.0%}, 부족: {', '.join(coverage.needs_work) or '없음'}",
        })

        log.info(
            "adaptive_iter_done",
            iteration=i,
            coverage=f"{coverage.coverage_ratio:.2f}",
            missing=coverage.needs_work,
            new_chunks=len(new_chunks),
            total_chunks=len(all_chunks),
        )

    return {
        "profile": profile,
        "iterations": iteration_history,
        "total_chunks": len(all_chunks),
        "coverage": coverage.coverage_ratio,
        "sources": list(visited_urls),
        "search_results": all_search_results,
        "crawled_chunks": all_chunks,
    }


async def analyze_coverage(
    person_name: str,
    profile: dict,
    llm: BaseLLMClient,
) -> ProfileCoverage:
    """LLM으로 프로필 필드별 품질 평가."""
    # 프로필에서 분석 대상 필드만 추출
    profile_subset = {k: profile.get(k, "") for k in PERSONA_FIELDS}
    profile_json = json.dumps(profile_subset, ensure_ascii=False, indent=2)

    try:
        response = await llm.complete([
            {"role": "system", "content": "페르소나 프로필 품질 분석가. JSON으로만 응답."},
            {"role": "user", "content": COVERAGE_ANALYSIS_PROMPT.format(
                person_name=person_name,
                profile_json=profile_json,
            )},
        ], temperature=0.2, max_tokens=1500)

        data = _parse_json(response)
        field_scores_raw = data.get("field_scores", {})

        cov = ProfileCoverage()
        for f in PERSONA_FIELDS:
            info = field_scores_raw.get(f, {})
            if isinstance(info, dict):
                cov.field_scores[f] = float(info.get("score", 0))
                cov.field_reasons[f] = info.get("reason", "")
            elif isinstance(info, (int, float)):
                cov.field_scores[f] = float(info)
            else:
                cov.field_scores[f] = 0.0

        cov.missing = [f for f in PERSONA_FIELDS if cov.field_scores.get(f, 0) < 0.3]
        cov.weak = [f for f in PERSONA_FIELDS if 0.3 <= cov.field_scores.get(f, 0) < 0.5]

        return cov

    except Exception as exc:
        log.warning("coverage_analysis_failed", error=str(exc)[:120])
        # Fallback: 빈 필드를 missing으로 처리
        cov = ProfileCoverage()
        for f in PERSONA_FIELDS:
            val = profile.get(f)
            if not val or (isinstance(val, str) and len(val) < 10):
                cov.field_scores[f] = 0.1
                cov.missing.append(f)
            elif isinstance(val, list) and len(val) < 2:
                cov.field_scores[f] = 0.3
                cov.weak.append(f)
            else:
                cov.field_scores[f] = 0.7
        return cov


async def generate_gap_queries(
    person_name: str,
    missing_fields: list[str],
    existing_sources: list[str],
    llm: BaseLLMClient,
) -> list[str]:
    """부족한 필드를 채우기 위한 타겟 검색 키워드 생성."""
    # 필드별 검색 전략 설명 생성
    missing_desc_parts = []
    for f in missing_fields:
        strategies = FIELD_SEARCH_STRATEGIES.get(f, [])
        hint = ", ".join(strategies[:3]) if strategies else f
        field_label = {
            "role": "직함/직책",
            "description": "배경/영향력",
            "personality": "성격 특성",
            "decision_style": "의사결정 스타일",
            "speech_style": "말투/커뮤니케이션",
            "core_values": "핵심 가치관",
            "known_stances": "주요 입장/견해",
            "blind_spots": "약점/편향/비판",
            "stance": "전략적 포지션",
            "goals": "추구 목표",
            "knowledge": "전문 분야",
        }.get(f, f)
        missing_desc_parts.append(f"- {field_label}: 관련 키워드 힌트 ({hint})")

    missing_desc = "\n".join(missing_desc_parts)
    sources_str = "\n".join(f"- {s}" for s in existing_sources[:10]) if existing_sources else "없음"

    try:
        response = await llm.complete([
            {"role": "system", "content": "검색 키워드 전문가. JSON 배열로만 응답."},
            {"role": "user", "content": GAP_QUERY_PROMPT.format(
                person_name=person_name,
                missing_fields_desc=missing_desc,
                existing_sources=sources_str,
            )},
        ], temperature=0.3, max_tokens=500)

        queries = _parse_json(response)
        if isinstance(queries, list):
            return [str(q) for q in queries if q][:8]
    except Exception as exc:
        log.warning("gap_query_gen_failed", error=str(exc)[:120])

    # Fallback: 필드별 전략 키워드로 직접 조합
    fallback = []
    for f in missing_fields[:4]:
        strategies = FIELD_SEARCH_STRATEGIES.get(f, [f])
        for s in strategies[:2]:
            fallback.append(f"{person_name} {s}")
    return fallback[:8]


def merge_profiles(
    existing: dict,
    new_profile: dict,
    coverage: ProfileCoverage,
) -> dict:
    """기존 프로필에 새 프로필 병합. 약한 필드만 업데이트."""
    merged = {**existing}

    for f in PERSONA_FIELDS:
        old_score = coverage.field_scores.get(f, 0)
        new_val = new_profile.get(f)
        old_val = existing.get(f)

        # 기존 필드가 약하면 (0.5 미만) 새 값으로 교체
        if old_score < 0.5 and new_val:
            merged[f] = new_val
        # 기존 필드가 보통이고 새 값이 더 풍부하면 교체
        elif old_score < 0.7 and new_val:
            if _value_richness(new_val) > _value_richness(old_val):
                merged[f] = new_val

    # 메타 필드 보존
    for key in ["name", "source_count", "sources"]:
        if key in new_profile:
            merged[key] = new_profile[key]

    return merged


def _value_richness(val) -> int:
    """값의 풍부함 측정 (길이/항목수)."""
    if val is None:
        return 0
    if isinstance(val, str):
        return len(val)
    if isinstance(val, list):
        return sum(len(str(v)) for v in val)
    if isinstance(val, dict):
        return sum(len(str(k)) + len(str(v)) for k, v in val.items())
    return len(str(val))


def _collect_urls(result: dict, visited: set[str]):
    """검색 결과에서 URL 수집."""
    for r in result.get("search_results", []):
        url = r.get("url", "")
        if url:
            visited.add(url)


def _parse_json(text: str) -> dict | list:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)
