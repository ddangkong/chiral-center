"""Deduplication for normalized search results.

Two-pass strategy:
  1) Hard dedupe by canonical URL (`normalize.canonical_url`)
  2) Soft dedupe by title signature — when the same article is republished
     under different URLs (e.g. mirror sites), drop the lower-authority copy.

Provider preference: when two results collide, prefer in this order:
  openai_web > ddg
This way, when the OpenAI Responses web_search returns a richer hit for the
same URL, we keep the openai_web copy and drop the DDG one.
"""
from __future__ import annotations

from utils.logger import log
from core.research.search.base import NormalizedResult
from core.research.normalize import canonical_url, title_signature


# Higher = preferred when collision happens
_PROVIDER_RANK = {
    "openai_web": 2,
    "ddg": 1,
}


def _rank(result: NormalizedResult) -> int:
    return _PROVIDER_RANK.get(result.provider, 0)


def dedupe_results(results: list[NormalizedResult]) -> list[NormalizedResult]:
    """Remove duplicates by URL and by title signature.

    Stable: input order within each unique key is preserved.
    Returns a new list; does not mutate the input.
    """
    if not results:
        return []

    # Pass 1: canonical URL dedupe
    by_url: dict[str, NormalizedResult] = {}
    for r in results:
        key = canonical_url(r.url) or r.url
        if not key:
            continue
        existing = by_url.get(key)
        if existing is None:
            by_url[key] = r
            continue
        # Prefer higher-ranked provider; on tie, prefer the one with more snippet text
        if _rank(r) > _rank(existing):
            by_url[key] = r
        elif _rank(r) == _rank(existing) and len(r.snippet or "") > len(existing.snippet or ""):
            by_url[key] = r

    after_url = list(by_url.values())

    # Pass 2: title signature dedupe (handles mirror sites with different URLs)
    by_sig: dict[str, NormalizedResult] = {}
    sig_collisions = 0
    for r in after_url:
        sig = title_signature(r.title)
        if not sig:
            # Articles with no title get keyed by URL — never collide
            by_sig[f"__urlonly__::{r.url}"] = r
            continue
        existing = by_sig.get(sig)
        if existing is None:
            by_sig[sig] = r
        else:
            sig_collisions += 1
            if _rank(r) > _rank(existing):
                by_sig[sig] = r

    out = list(by_sig.values())

    log.info(
        "dedupe_done",
        input_count=len(results),
        after_url_dedupe=len(after_url),
        after_title_dedupe=len(out),
        url_dropped=len(results) - len(after_url),
        title_dropped=sig_collisions,
    )
    return out
