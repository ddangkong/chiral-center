"""
auto_search.py — 인물 이름 기반 자동 검색 + 크롤링.

3단계 폴백: DDG → Google News RSS → OpenAI web_search
"""

import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus

import httpx

from utils.logger import log
from core.crawler import fetch_youtube_transcript, fetch_web_article


async def search_web(
    person_name: str,
    keywords: list[str],
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    max_results: int = 15,
    openai_api_key: str | None = None,
) -> list[dict]:
    """웹 검색으로 관련 기사/페이지 URL 수집.

    DDG를 먼저 시도하고, 결과가 부족하면(3개 미만) OpenAI Responses API
    web_search_preview로 폴백. Railway 같은 서버 환경에서 DDG가 rate-limit
    되는 경우를 커버한다.

    Returns: [{"title": "...", "url": "...", "snippet": "..."}]
    """
    loop = asyncio.get_event_loop()

    # 기본 검색어 + 추가 키워드 조합
    queries = []
    if keywords:
        for kw in keywords:
            queries.append(f'"{person_name}" {kw}')
    base_queries = [
        f'"{person_name}" 발언 전략 경영',
        f'"{person_name}" 최근 뉴스 기사',
        f'"{person_name}" 프로필 이력',
    ]
    for q in base_queries:
        if q not in queries:
            queries.append(q)

    timelimit = _date_to_timelimit(date_from, date_to)
    per_query = max(4, max_results // max(len(queries), 1) + 2)

    all_results: list[dict] = []

    # ── 1차: DDG 시도 ──
    ddg_results = await _search_ddg(queries, person_name, per_query, timelimit, loop)
    all_results.extend(ddg_results)
    log.info("web_search_ddg_done", person=person_name, results=len(ddg_results))

    # ── 2차: DDG 부족하면 Google News RSS 폴백 (무료, IP 차단 없음) ──
    if len(all_results) < 3:
        log.info("web_search_google_rss_fallback", person=person_name, ddg_count=len(all_results))
        rss_results = await _search_google_rss(person_name, keywords, max_results=max_results)
        all_results.extend(rss_results)
        log.info("web_search_google_rss_done", person=person_name, rss_results=len(rss_results), total=len(all_results))

    # ── 3차: 그래도 부족하면 OpenAI web_search 폴백 (유료) ──
    if len(all_results) < 3 and openai_api_key:
        log.info("web_search_openai_fallback", person=person_name, current_count=len(all_results))
        openai_results = await _search_openai_web(queries[:5], person_name, openai_api_key)
        all_results.extend(openai_results)

    # URL 중복 제거
    seen: set[str] = set()
    unique: list[dict] = []
    for r in all_results:
        url = r.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(r)

    log.info("web_search_done", person=person_name, results=len(unique), queries=len(queries))
    return unique[:max_results]


async def _search_ddg(
    queries: list[str],
    person_name: str,
    per_query: int,
    timelimit,
    loop,
) -> list[dict]:
    """DDG 검색 내부 헬퍼. 실패 시 빈 리스트."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        log.warning("ddg_import_failed")
        return []

    def _search():
        results = []
        try:
            with DDGS() as ddgs:
                for query in queries:
                    try:
                        hits = list(ddgs.text(query, region="kr-kr", timelimit=timelimit, max_results=per_query))
                        for h in hits:
                            results.append({
                                "title": h.get("title", ""),
                                "url": h.get("href", ""),
                                "snippet": h.get("body", ""),
                                "source_type": "web",
                                "query": query,
                            })
                    except Exception as e:
                        log.warning("ddg_search_error", query=query, error=str(e))

                # 영어 검색 추가
                try:
                    en_hits = list(ddgs.text(
                        f"{person_name} interview strategy vision",
                        region="wt-wt", timelimit=timelimit, max_results=5,
                    ))
                    for h in en_hits:
                        results.append({
                            "title": h.get("title", ""),
                            "url": h.get("href", ""),
                            "snippet": h.get("body", ""),
                            "source_type": "web",
                            "query": f"{person_name} (EN)",
                        })
                except Exception as e:
                    log.warning("ddg_en_search_error", error=str(e))
        except Exception as e:
            log.warning("ddg_session_failed", error=str(e))
        return results

    try:
        return await loop.run_in_executor(None, _search)
    except Exception as e:
        log.warning("ddg_executor_failed", error=str(e))
        return []


async def _search_openai_web(
    queries: list[str],
    person_name: str,
    api_key: str,
) -> list[dict]:
    """OpenAI Responses API web_search 폴백. DDG가 실패했을 때만 호출."""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return []

    client = AsyncOpenAI(api_key=api_key)
    all_results: list[dict] = []

    for query in queries[:3]:  # 비용 절약: 최대 3개 쿼리만
        try:
            response = await client.responses.create(
                model="gpt-4o-mini",
                input=[
                    {"role": "developer", "content": [{"type": "input_text", "text":
                        f"Search the web for: {query}\n"
                        "Return ONLY a JSON array of results: "
                        '[{"title":"...","url":"https://...","snippet":"..."}]\n'
                        "No prose. Max 5 results. Real URLs only."
                    }]},
                    {"role": "user", "content": [{"type": "input_text", "text": query}]},
                ],
                tools=[{"type": "web_search_preview"}],
                background=False,
            )
            text = getattr(response, "output_text", "") or ""
            import json as _json, re as _re
            # JSON 배열 추출
            text = text.strip()
            if text.startswith("```"):
                text = _re.sub(r"^```(?:json)?\s*", "", text)
                text = _re.sub(r"\s*```$", "", text)
            # 배열 또는 객체에서 results 키 추출
            try:
                parsed = _json.loads(text)
                items = parsed if isinstance(parsed, list) else parsed.get("results", [])
            except _json.JSONDecodeError:
                match = _re.search(r"\[[\s\S]*\]", text)
                items = _json.loads(match.group(0)) if match else []

            for item in items[:5]:
                url = (item.get("url") or "").strip()
                if url:
                    all_results.append({
                        "title": (item.get("title") or "").strip(),
                        "url": url,
                        "snippet": (item.get("snippet") or "").strip(),
                        "source_type": "web",
                        "query": query,
                    })
            log.info("openai_web_persona_search", query=query, hits=len(items))

            # 소스 annotation에서도 URL 추출 (JSON 파싱 실패 시 폴백)
            if not all_results:
                for item in (response.output or []):
                    if getattr(item, "type", "") != "message":
                        continue
                    for block in (getattr(item, "content", []) or []):
                        for ann in (getattr(block, "annotations", []) or []):
                            url = (getattr(ann, "url", "") or "").strip()
                            if url:
                                all_results.append({
                                    "title": (getattr(ann, "title", "") or "").strip(),
                                    "url": url,
                                    "snippet": "",
                                    "source_type": "web",
                                    "query": query,
                                })
        except Exception as e:
            log.warning("openai_web_persona_search_failed", query=query, error=str(e)[:200])

    return all_results


async def search_youtube(
    person_name: str,
    keywords: list[str],
    max_results: int = 8,
) -> list[dict]:
    """DuckDuckGo 비디오 검색으로 YouTube 영상 URL 수집.

    키워드별로 충분한 영상을 검색합니다.

    Returns: [{"title": "...", "url": "...", "duration": "..."}]
    """
    from duckduckgo_search import DDGS

    loop = asyncio.get_event_loop()

    queries = []
    if keywords:
        for kw in keywords:
            queries.append(f"{person_name} {kw}")
    # 기본 영상 검색 쿼리
    base_yt = [
        f"{person_name} 인터뷰",
        f"{person_name} 강연",
        f"{person_name} interview",
    ]
    for q in base_yt:
        if q not in queries:
            queries.append(q)

    per_query = max(3, max_results // max(len(queries), 1) + 2)

    def _search():
        results = []
        with DDGS() as ddgs:
            for query in queries:
                try:
                    hits = list(ddgs.videos(
                        query,
                        region="kr-kr",
                        max_results=per_query,
                    ))
                    for h in hits:
                        url = h.get("content", "")
                        if "youtube.com" in url or "youtu.be" in url:
                            results.append({
                                "title": h.get("title", ""),
                                "url": url,
                                "duration": h.get("duration", ""),
                                "source_type": "youtube",
                                "query": query,
                            })
                except Exception as e:
                    log.warning("yt_search_error", query=query, error=str(e))
        return results

    all_results = await loop.run_in_executor(None, _search)

    seen = set()
    unique = []
    for r in all_results:
        url = r["url"]
        if url and url not in seen:
            seen.add(url)
            unique.append(r)

    log.info("youtube_search_done", person=person_name, results=len(unique))
    return unique[:max_results]


async def auto_collect(
    person_name: str,
    sources: list[str],  # ["web", "youtube"]
    keywords: list[str],
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    max_web: int = 15,
    max_youtube: int = 8,
    exclude_urls: set[str] | None = None,
    openai_api_key: str | None = None,
) -> dict:
    """자동 검색 → 크롤링 파이프라인.

    openai_api_key가 있으면 DDG 결과 부족 시 OpenAI web_search로 폴백.

    Returns: {
        "search_results": [...],  # 검색 결과 목록
        "crawled_chunks": [...],  # 크롤링된 텍스트 청크
        "stats": {"web_found": N, "yt_found": N, "crawled": N, "failed": N}
    }
    """
    search_results = []
    stats = {"web_found": 0, "yt_found": 0, "crawled": 0, "failed": 0}

    # 1. 검색
    tasks = []
    if "web" in sources:
        tasks.append(("web", search_web(person_name, keywords, date_from, date_to, max_web, openai_api_key=openai_api_key)))
    if "youtube" in sources:
        tasks.append(("youtube", search_youtube(person_name, keywords, max_youtube)))

    for source_type, task in tasks:
        try:
            results = await task
            search_results.extend(results)
            if source_type == "web":
                stats["web_found"] = len(results)
            else:
                stats["yt_found"] = len(results)
        except Exception as e:
            log.warning("search_failed", source=source_type, error=str(e))

    # 이미 방문한 URL 제외
    if exclude_urls:
        search_results = [r for r in search_results if r["url"] not in exclude_urls]

    if not search_results:
        return {"search_results": [], "crawled_chunks": [], "stats": stats}

    # 2. 크롤링 (병렬) — RSS snippet은 크롤링 없이 직접 chunk화
    crawl_tasks = []
    rss_direct_chunks = []
    for r in search_results:
        url = r["url"]
        if r.get("_rss_snippet"):
            # Google RSS: URL은 resolve 불가하지만 snippet + title에 기사 내용 있음
            snippet = r.get("snippet", "").strip()
            title = r.get("title", "").strip()
            if snippet or title:
                text = f"{title}\n{snippet}" if title and snippet else (title or snippet)
                rss_direct_chunks.append({
                    "text": text,
                    "source": f"rss:{title[:50]}",
                    "title": title,
                    "published_at": r.get("published_at"),
                })
        elif r["source_type"] == "youtube":
            crawl_tasks.append((url, fetch_youtube_transcript(url)))
        else:
            crawl_tasks.append((url, fetch_web_article(url)))

    all_chunks = []
    # 인물 이름의 변형 패턴 (성+이름, 이름, 성씨, 영문 등)
    name_parts = person_name.strip().split()
    name_variants = {person_name.lower(), person_name.replace(" ", "").lower()}
    for p in name_parts:
        if len(p) >= 2:
            name_variants.add(p.lower())

    # RSS direct chunks는 관련성 필터 적용 후 추가
    for chunk in rss_direct_chunks:
        text_lower = chunk.get("text", "").lower()
        if any(v in text_lower for v in name_variants):
            all_chunks.append(chunk)
            stats["crawled"] += 1
    if rss_direct_chunks:
        log.info("rss_direct_chunks", total=len(rss_direct_chunks),
                 relevant=len([c for c in rss_direct_chunks if any(v in c.get("text","").lower() for v in name_variants)]))

    for url, task in crawl_tasks:
        try:
            chunks = await task
            # 관련성 필터: 인물 이름이 본문에 한 번도 안 나타나면 제외
            # DDG가 무관한 페이지(게임 포럼 등)를 반환하는 경우를 걸러냄
            relevant_chunks = []
            for chunk in chunks:
                text_lower = chunk.get("text", "").lower()
                if any(v in text_lower for v in name_variants):
                    relevant_chunks.append(chunk)
            if relevant_chunks:
                all_chunks.extend(relevant_chunks)
                stats["crawled"] += 1
            elif chunks:
                # 본문은 있지만 인물 이름 미포함 → 건너뜀
                log.info("auto_crawl_irrelevant", url=url,
                         chunks=len(chunks), person=person_name,
                         reason="person name not found in crawled text")
                stats["failed"] += 1
            else:
                stats["failed"] += 1
        except Exception as e:
            log.warning("auto_crawl_failed", url=url, error=str(e))
            stats["failed"] += 1

    log.info("auto_collect_done", person=person_name, stats=stats,
             relevant_chunks=len(all_chunks))
    return {
        "search_results": search_results,
        "crawled_chunks": all_chunks,
        "stats": stats,
    }


def _date_to_timelimit(date_from: Optional[str], date_to: Optional[str]) -> Optional[str]:
    """날짜 범위를 DuckDuckGo timelimit으로 변환."""
    if not date_from:
        return None

    try:
        dt_from = datetime.strptime(date_from, "%Y-%m-%d")
        now = datetime.now()
        diff = (now - dt_from).days

        if diff <= 7:
            return "w"
        elif diff <= 30:
            return "m"
        elif diff <= 365:
            return "y"
        else:
            return None  # DuckDuckGo doesn't support arbitrary ranges
    except Exception:
        return None


# ── Google News RSS 검색 (2차 폴백) ─────────────────────────────────
# API 키 불요, IP 차단 없음, 뉴스 기사 위주

_GOOGLE_RSS_URL = "https://news.google.com/rss/search?q={query}&hl={hl}&gl={gl}&ceid={ceid}"

_GOOGLE_RSS_LOCALES = [
    {"hl": "ko", "gl": "KR", "ceid": "KR:ko"},   # 한국어
    {"hl": "en", "gl": "US", "ceid": "US:en"},    # 영어
]


async def _search_google_rss(
    person_name: str,
    keywords: list[str],
    max_results: int = 15,
) -> list[dict]:
    """Google News RSS로 인물 관련 뉴스 검색.

    한국어 + 영어 두 locale을 병행해서 글로벌 인물도 커버.
    RSS XML을 파싱해서 title/url/snippet/published_at 추출.
    """
    queries = [person_name]
    if keywords:
        for kw in keywords[:3]:
            queries.append(f"{person_name} {kw}")

    all_results: list[dict] = []
    seen_urls: set[str] = set()

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for locale in _GOOGLE_RSS_LOCALES:
            for query in queries:
                url = _GOOGLE_RSS_URL.format(
                    query=quote_plus(query),
                    hl=locale["hl"],
                    gl=locale["gl"],
                    ceid=locale["ceid"],
                )
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        log.warning("google_rss_http_error", query=query, status=resp.status_code)
                        continue

                    items = _parse_rss_xml(resp.text)
                    for item in items:
                        item_url = item.get("url", "")
                        if item_url and item_url not in seen_urls:
                            seen_urls.add(item_url)
                            all_results.append(item)

                except Exception as e:
                    log.warning("google_rss_error", query=query, error=str(e)[:200])

                if len(all_results) >= max_results:
                    break
            if len(all_results) >= max_results:
                break

    log.info("google_rss_search_done", person=person_name, results=len(all_results))
    return all_results[:max_results]


def _parse_rss_xml(xml_text: str) -> list[dict]:
    """Google News RSS XML → list of {title, url, snippet, source_type, published_at}."""
    results: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
        # RSS 2.0: <rss><channel><item>...
        channel = root.find("channel")
        if channel is None:
            return results
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()

            if not link:
                continue

            # pubDate 파싱: "Sat, 05 Apr 2025 07:00:00 GMT" → "2025-04-05"
            published_at = None
            if pub_date:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(pub_date)
                    published_at = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass

            # description에서 HTML 태그 제거 (간단한 strip)
            import re as _re
            snippet = _re.sub(r"<[^>]+>", "", description).strip()[:300]

            # Google RSS article URL은 news.google.com 리다이렉트라
            # 서버에서 resolve 불가. 원본 기사 URL 대신 RSS snippet을
            # 직접 chunk로 쓸 수 있도록 _rss_snippet 필드 추가.
            results.append({
                "title": title,
                "url": link,
                "snippet": snippet,
                "source_type": "web",
                "published_at": published_at,
                "query": "google_rss",
                "_rss_snippet": True,  # 크롤링 skip 플래그
            })
    except ET.ParseError as e:
        log.warning("google_rss_xml_parse_error", error=str(e)[:200])
    return results
