"""Normalization helpers — provider-specific result → common schema.

The actual `NormalizedResult` dataclass lives in `search.base`. This module
hosts the cross-cutting helpers used by *both* the providers and the
orchestrator (URL canonicalization, source-type classification, etc.).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from utils.logger import log
from core.research.search.base import NormalizedResult


# ── Source type classification (URL domain heuristic) ──────────────────────

# (substring → category) — first match wins, longest patterns first.
_SOURCE_TYPE_PATTERNS: list[tuple[str, str]] = [
    # gov / public
    (".gov", "gov"),
    (".gov.kr", "gov"),
    (".go.kr", "gov"),
    ("oecd.org", "gov"),
    ("worldbank.org", "gov"),
    ("imf.org", "gov"),
    ("un.org", "gov"),
    ("europa.eu", "gov"),
    ("kostat.go.kr", "gov"),
    ("kotra.or.kr", "gov"),
    # research / academia
    (".edu", "research"),
    (".ac.kr", "research"),
    ("arxiv.org", "research"),
    ("nature.com", "research"),
    ("sciencedirect.com", "research"),
    ("ssrn.com", "research"),
    ("mckinsey.com", "research"),
    ("bcg.com", "research"),
    ("statista.com", "research"),
    ("kpmg.com", "research"),
    ("deloitte.com", "research"),
    ("pwc.com", "research"),
    ("euromonitor.com", "research"),
    ("nielsen.com", "research"),
    ("gartner.com", "research"),
    ("forrester.com", "research"),
    ("idc.com", "research"),
    # media
    ("bloomberg.com", "media"),
    ("reuters.com", "media"),
    ("ft.com", "media"),
    ("wsj.com", "media"),
    ("nytimes.com", "media"),
    ("economist.com", "media"),
    ("cnbc.com", "media"),
    ("bbc.com", "media"),
    ("bbc.co.uk", "media"),
    ("forbes.com", "media"),
    ("techcrunch.com", "media"),
    ("theverge.com", "media"),
    ("wired.com", "media"),
    ("yna.co.kr", "media"),  # 연합뉴스
    ("chosun.com", "media"),
    ("joongang.co.kr", "media"),
    ("hani.co.kr", "media"),
    ("mk.co.kr", "media"),
    ("hankyung.com", "media"),
    ("etnews.com", "media"),
    # retailer / marketplace
    ("amazon.", "retailer"),
    ("ebay.", "retailer"),
    ("alibaba.", "retailer"),
    ("coupang.com", "retailer"),
    ("11st.co.kr", "retailer"),
    ("gmarket.co.kr", "retailer"),
    ("ssg.com", "retailer"),
    ("flipkart.com", "retailer"),
    ("walmart.com", "retailer"),
    # blog
    ("medium.com", "blog"),
    ("substack.com", "blog"),
    ("wordpress.com", "blog"),
    ("blog.naver.com", "blog"),
    ("tistory.com", "blog"),
    ("brunch.co.kr", "blog"),
    ("velog.io", "blog"),
]


def classify_source_type(url: str) -> str:
    """Classify a URL's authority bucket using domain substring matching.

    Returns one of: gov, company, media, retailer, research, blog, unknown.
    Defaults to "company" for "*.com / *.co.kr / *.io" that aren't otherwise
    classified — these are typically corporate sites.
    """
    if not url:
        return "unknown"
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return "unknown"
    if not host:
        return "unknown"

    for pattern, kind in _SOURCE_TYPE_PATTERNS:
        if pattern in host:
            return kind

    # Soft default: if it's a typical corporate TLD, call it "company"
    if any(host.endswith(suffix) for suffix in (".com", ".co.kr", ".io", ".net", ".kr")):
        return "company"
    return "unknown"


# ── Canonical URL — for dedupe ─────────────────────────────────────────────

# These query params are tracking junk and should be stripped before comparing URLs.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "gclid", "fbclid", "mc_cid", "mc_eid", "_hsenc", "_hsmi",
    "ref", "ref_src", "ref_url", "referrer", "source", "campaign",
    "yclid", "msclkid", "igshid", "spm", "share_from",
}


def canonical_url(url: str) -> str:
    """Strip tracking params, lowercase host, drop fragments, normalize trailing slash.

    Two URLs that point to the same logical resource should produce the same
    canonical form, so the dedupe step can group them.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return url.strip()

    # Reject anything that doesn't look like a real URL
    if not parsed.netloc:
        return url.strip()

    scheme = (parsed.scheme or "https").lower()
    if scheme not in ("http", "https"):
        return url.strip()

    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    # Filter query params
    query_pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False)
                   if k.lower() not in _TRACKING_PARAMS]
    # Sort for stable comparison
    query_pairs.sort()
    query = urlencode(query_pairs)

    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    return urlunparse((scheme, host, path, "", query, ""))


# ── Title / snippet similarity (for soft dedupe) ───────────────────────────

_PUNCT_RE = re.compile(r"[^\w\s가-힣]+", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace. For similarity hashing."""
    if not text:
        return ""
    cleaned = _PUNCT_RE.sub(" ", text.lower())
    return _WS_RE.sub(" ", cleaned).strip()


def title_signature(title: str) -> str:
    """Compact signature used to detect 'same article, different URL'."""
    norm = normalize_text(title)
    # Drop very common stopwords that bloat similarity
    tokens = [t for t in norm.split() if len(t) > 1]
    return " ".join(tokens[:12])  # first 12 meaningful tokens


def normalize_results(results: list[NormalizedResult]) -> list[NormalizedResult]:
    """Apply canonical URL + source classification to a batch in place.

    Providers usually call `classify_source_type` already, but this is a safety
    net that also fixes any URL the dedupe step needs.
    """
    for r in results:
        r.url = canonical_url(r.url) or r.url
        if r.source_type in (None, "", "unknown"):
            r.source_type = classify_source_type(r.url)
    log.info("normalize_done", count=len(results))
    return results
