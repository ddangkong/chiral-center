"""Unit tests for research/dedupe.py — URL + title signature dedup."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from core.research.dedupe import dedupe_results
from core.research.search.base import NormalizedResult


def _r(provider, url, title="", snippet="", sq="SQ1") -> NormalizedResult:
    return NormalizedResult(
        subquestion_id=sq,
        provider=provider,
        query="test",
        title=title,
        url=url,
        snippet=snippet,
    )


def test_url_dedupe_keeps_one():
    results = [
        _r("ddg", "https://example.com/foo"),
        _r("ddg", "https://example.com/foo"),
    ]
    out = dedupe_results(results)
    assert len(out) == 1


def test_url_dedupe_normalizes_tracking_params():
    results = [
        _r("ddg", "https://example.com/foo?utm_source=a"),
        _r("ddg", "https://example.com/foo?utm_source=b"),
    ]
    out = dedupe_results(results)
    assert len(out) == 1


def test_url_dedupe_prefers_openai_web_over_ddg():
    results = [
        _r("ddg", "https://example.com/foo", title="DDG version", snippet="ddg snippet"),
        _r("openai_web", "https://example.com/foo", title="OpenAI version", snippet="openai snippet"),
    ]
    out = dedupe_results(results)
    assert len(out) == 1
    assert out[0].provider == "openai_web"


def test_url_dedupe_prefers_richer_snippet_within_same_provider():
    results = [
        _r("ddg", "https://example.com/foo", snippet="short"),
        _r("ddg", "https://example.com/foo", snippet="this is a much longer and more useful snippet"),
    ]
    out = dedupe_results(results)
    assert len(out) == 1
    assert "longer" in out[0].snippet


def test_title_signature_dedupe_handles_mirror_sites():
    title = "인도 라면 시장 2025 분석 보고서"
    results = [
        _r("ddg", "https://site-a.com/article-1", title=title),
        _r("ddg", "https://mirror-b.com/different-path", title=title),
    ]
    out = dedupe_results(results)
    # Different URLs but same title — should be 1
    assert len(out) == 1


def test_title_signature_dedupe_keeps_distinct_titles():
    results = [
        _r("ddg", "https://a.com/x", title="인도 라면 시장 분석"),
        _r("ddg", "https://b.com/y", title="브라질 라면 시장 분석"),
    ]
    out = dedupe_results(results)
    assert len(out) == 2


def test_empty_input_returns_empty():
    assert dedupe_results([]) == []


def test_results_with_no_url_dropped():
    results = [
        _r("ddg", "", title="No URL"),
        _r("ddg", "https://valid.com/x", title="Valid"),
    ]
    out = dedupe_results(results)
    assert len(out) == 1
    assert out[0].url == "https://valid.com/x"


def test_mixed_provider_collision_chooses_openai_web():
    results = [
        _r("ddg", "https://news.com/article", title="Same article", snippet="ddg"),
        _r("ddg", "https://news.com/article", title="Same article", snippet="ddg2"),
        _r("openai_web", "https://news.com/article", title="Same article", snippet="openai"),
    ]
    out = dedupe_results(results)
    assert len(out) == 1
    assert out[0].provider == "openai_web"


if __name__ == "__main__":
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
