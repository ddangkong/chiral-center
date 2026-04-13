"""Unit tests for research/normalize.py — URL canonicalization + source classification."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from core.research.normalize import (
    canonical_url,
    classify_source_type,
    normalize_text,
    title_signature,
    normalize_results,
)
from core.research.search.base import NormalizedResult


# ── canonical_url ────────────────────────────────────────────────

def test_canonical_url_strips_tracking_params():
    raw = "https://example.com/article?utm_source=newsletter&utm_medium=email&id=42"
    assert canonical_url(raw) == "https://example.com/article?id=42"


def test_canonical_url_lowercases_host_and_drops_www():
    assert canonical_url("HTTPS://www.Example.COM/foo") == "https://example.com/foo"


def test_canonical_url_drops_fragment_and_normalizes_trailing_slash():
    assert canonical_url("https://example.com/foo/#section") == "https://example.com/foo"


def test_canonical_url_sorts_query_for_stability():
    a = canonical_url("https://example.com/?b=2&a=1")
    b = canonical_url("https://example.com/?a=1&b=2")
    assert a == b


def test_canonical_url_handles_empty():
    assert canonical_url("") == ""
    assert canonical_url("not-a-url") == "not-a-url"


# ── classify_source_type ─────────────────────────────────────────

def test_classify_gov():
    assert classify_source_type("https://www.kotra.or.kr/foo") == "gov"
    assert classify_source_type("https://kostat.go.kr/data") == "gov"
    assert classify_source_type("https://oecd.org/report") == "gov"


def test_classify_research():
    assert classify_source_type("https://arxiv.org/abs/1234") == "research"
    assert classify_source_type("https://www.statista.com/chart/123") == "research"
    assert classify_source_type("https://mit.edu/paper") == "research"


def test_classify_media():
    assert classify_source_type("https://www.bloomberg.com/news/x") == "media"
    assert classify_source_type("https://reuters.com/business") == "media"
    assert classify_source_type("https://yna.co.kr/view/123") == "media"


def test_classify_retailer():
    assert classify_source_type("https://www.amazon.com/dp/B01") == "retailer"
    assert classify_source_type("https://coupang.com/products/x") == "retailer"


def test_classify_blog():
    assert classify_source_type("https://medium.com/@user/post") == "blog"
    assert classify_source_type("https://blog.naver.com/foo/bar") == "blog"


def test_classify_company_default():
    # Random corporate-looking domain → company default
    assert classify_source_type("https://acme-corp.com/about") == "company"
    assert classify_source_type("https://startup.io/product") == "company"


def test_classify_unknown():
    assert classify_source_type("") == "unknown"
    assert classify_source_type("not-a-url") == "unknown"


# ── text helpers ─────────────────────────────────────────────────

def test_normalize_text_strips_punctuation_and_lowercases():
    assert normalize_text("Hello, World!! 인도 시장.") == "hello world 인도 시장"


def test_title_signature_caps_at_12_tokens():
    long_title = " ".join(f"word{i}" for i in range(20))
    sig = title_signature(long_title)
    assert len(sig.split()) == 12


def test_title_signature_drops_single_chars():
    assert "a" not in title_signature("a hello b world").split()


# ── normalize_results (in-place URL canonicalization) ────────────

def test_normalize_results_canonicalizes_and_classifies():
    results = [
        NormalizedResult(
            subquestion_id="SQ1",
            provider="ddg",
            query="test",
            title="Article",
            url="https://www.bloomberg.com/news/x?utm_source=foo",
            snippet="...",
            source_type="unknown",
        )
    ]
    out = normalize_results(results)
    assert out[0].url == "https://bloomberg.com/news/x"
    assert out[0].source_type == "media"


if __name__ == "__main__":
    # Allow running directly without pytest
    import inspect
    failures = 0
    passed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                passed += 1
                print(f"  PASS  {name}")
            except AssertionError as e:
                failures += 1
                print(f"  FAIL  {name}: {e}")
            except Exception as e:
                failures += 1
                print(f"  ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{passed} passed, {failures} failed")
    sys.exit(0 if failures == 0 else 1)
