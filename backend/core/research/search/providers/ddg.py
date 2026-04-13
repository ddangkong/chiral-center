"""DuckDuckGo search provider for the research orchestrator.

Searches in BOTH the local region (kr-kr) AND global (wt-wt) for every query,
deduplicates by URL, and returns the merged result set. This prevents the
"Korean gov site for Indonesian market data" problem where kr-kr results
dominate even when the query is about a foreign market.
"""
from __future__ import annotations

import asyncio

from utils.logger import log
from core.research.search.base import NormalizedResult
from core.research.normalize import classify_source_type


class DDGProvider:
    """DuckDuckGo text search via the `duckduckgo_search` library.

    Runs **two parallel region searches** (local + global) per query to get
    diverse, actually-relevant results. This is the always-on default provider.
    """

    name = "ddg"

    def __init__(self, *, region: str = "kr-kr", enabled: bool = True) -> None:
        self.enabled = enabled
        self.region = region

    async def search(
        self,
        query: str,
        subquestion_id: str,
        max_results: int = 5,
    ) -> list[NormalizedResult]:
        if not self.enabled:
            return []

        loop = asyncio.get_event_loop()
        try:
            from duckduckgo_search import DDGS
        except ImportError as exc:
            log.warning("ddg_import_failed", error=str(exc))
            return []

        # per-region allocation: half local, half global (at least 3 each)
        per_region = max(3, (max_results + 1) // 2)

        def _search_region(region: str, n: int) -> list[dict]:
            try:
                with DDGS() as ddgs:
                    return list(ddgs.text(query, region=region, max_results=n))
            except Exception as exc:
                log.warning("ddg_query_failed", query=query, region=region, error=str(exc)[:200])
                return []

        # Run both regions in parallel via thread executor
        local_fut = loop.run_in_executor(None, _search_region, self.region, per_region)
        global_fut = loop.run_in_executor(None, _search_region, "wt-wt", per_region)
        local_hits, global_hits = await asyncio.gather(local_fut, global_fut)

        # Merge + dedupe by URL (global results appended after local)
        seen_urls: set[str] = set()
        merged: list[dict] = []
        for h in local_hits + global_hits:
            url = (h.get("href") or h.get("url") or "").strip()
            if url and url not in seen_urls:
                seen_urls.add(url)
                merged.append(h)

        log.info(
            "ddg_search_complete",
            subquestion=subquestion_id,
            query=query,
            local_hits=len(local_hits),
            global_hits=len(global_hits),
            merged=len(merged),
        )

        results: list[NormalizedResult] = []
        for h in merged[:max_results * 2]:  # allow up to 2x to let dedupe pick
            url = h.get("href") or h.get("url") or ""
            if not url:
                continue
            results.append(
                NormalizedResult(
                    subquestion_id=subquestion_id,
                    provider=self.name,
                    query=query,
                    title=(h.get("title") or "").strip(),
                    url=url.strip(),
                    snippet=(h.get("body") or h.get("snippet") or "").strip(),
                    published_at=None,
                    source_type=classify_source_type(url),
                    raw=h,
                )
            )
        return results
