"""Common interface + dataclass for all research search providers.

Each provider (DuckDuckGo, OpenAI Responses web_search, ...) implements the
SearchProvider protocol and returns a list of NormalizedResult so downstream
modules (normalize/dedupe/evaluator) can stay provider-agnostic.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from utils.logger import log


@dataclass
class NormalizedResult:
    """Provider-agnostic search hit. Matches the spec schema 1:1."""

    subquestion_id: str
    provider: str  # "ddg" | "openai_web"
    query: str
    title: str
    url: str
    snippet: str
    published_at: str | None = None
    # gov | company | media | retailer | research | blog | unknown
    source_type: str = "unknown"
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "subquestion_id": self.subquestion_id,
            "provider": self.provider,
            "query": self.query,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "published_at": self.published_at,
            "source_type": self.source_type,
            "raw": self.raw,
        }


@runtime_checkable
class SearchProvider(Protocol):
    """All providers expose `name`, `enabled`, and an async `search` method."""

    name: str
    enabled: bool

    async def search(
        self,
        query: str,
        subquestion_id: str,
        max_results: int = 5,
    ) -> list[NormalizedResult]:
        ...


async def search_with_fallback(
    providers: list[SearchProvider],
    query: str,
    subquestion_id: str,
    max_results: int = 5,
    timeout_per_provider: float = 15.0,
) -> list[NormalizedResult]:
    """Run all enabled providers in parallel with per-provider timeout.

    If one provider fails or times out, the others still contribute results.
    Returns a flat list (no dedupe yet — that happens downstream).
    """
    enabled = [p for p in providers if getattr(p, "enabled", True)]
    if not enabled:
        log.warning("search_no_enabled_providers", subquestion=subquestion_id, query=query)
        return []

    async def _run_one(provider: SearchProvider) -> list[NormalizedResult]:
        try:
            return await asyncio.wait_for(
                provider.search(query, subquestion_id, max_results),
                timeout=timeout_per_provider,
            )
        except asyncio.TimeoutError:
            log.warning(
                "provider_timeout",
                provider=provider.name,
                query=query,
                timeout=timeout_per_provider,
            )
            return []
        except Exception as exc:
            log.warning(
                "provider_failed",
                provider=provider.name,
                query=query,
                error=str(exc)[:200],
            )
            return []

    log.info(
        "search_dispatch",
        subquestion=subquestion_id,
        query=query,
        providers=[p.name for p in enabled],
    )
    results_by_provider = await asyncio.gather(*[_run_one(p) for p in enabled])
    flat: list[NormalizedResult] = []
    for hits in results_by_provider:
        flat.extend(hits)
    log.info(
        "search_collected",
        subquestion=subquestion_id,
        query=query,
        total=len(flat),
        per_provider={p.name: len(h) for p, h in zip(enabled, results_by_provider)},
    )
    return flat
