"""Tests for evaluator output contract — coercion + classification rules.

These tests don't call the OpenAI API; they exercise the JSON-coercion path
that protects the orchestrator against malformed evaluator responses.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from core.research.evaluator import (
    EvaluationReport,
    ScoredResult,
    _coerce_report,
    _extract_json,
    _format_results_for_prompt,
)
from core.research.search.base import NormalizedResult


# ── _extract_json ────────────────────────────────────────────────

def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_fences():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_leading_text():
    text = 'Here is the result:\n{"results": [], "needs_more_search": false}'
    parsed = _extract_json(text)
    assert parsed == {"results": [], "needs_more_search": False}


def test_extract_json_returns_none_on_garbage():
    assert _extract_json("not json at all") is None
    assert _extract_json("") is None


# ── _coerce_report ───────────────────────────────────────────────

def test_coerce_report_full_valid_payload():
    payload = {
        "subquestion_id": "SQ1",
        "results": [
            {
                "url": "https://bloomberg.com/x",
                "title": "Article",
                "score_total": 8.5,
                "relevance": 9,
                "authority": 9,
                "freshness": 8,
                "evidence_density": 7,
                "classification": "high",
                "reason": "official source with numbers",
                "contradiction_flag": False,
            }
        ],
        "needs_more_search": False,
        "gap_reason": "",
    }
    report = _coerce_report(payload, "SQ1")
    assert isinstance(report, EvaluationReport)
    assert report.subquestion_id == "SQ1"
    assert len(report.results) == 1
    assert report.results[0].score_total == 8.5
    assert report.results[0].classification == "high"
    assert report.needs_more_search is False


def test_coerce_report_handles_missing_fields():
    payload = {
        "subquestion_id": "SQ2",
        "results": [
            {"url": "https://x.com", "title": "T"},  # missing scores
        ],
    }
    report = _coerce_report(payload, "SQ2")
    assert len(report.results) == 1
    r = report.results[0]
    assert r.url == "https://x.com"
    assert r.score_total == 0.0
    assert r.classification == "low"
    assert r.contradiction_flag is False


def test_coerce_report_drops_non_dict_results():
    payload = {
        "subquestion_id": "SQ3",
        "results": [
            {"url": "https://a.com", "title": "A"},
            "not a dict",
            None,
            {"url": "https://b.com", "title": "B"},
        ],
    }
    report = _coerce_report(payload, "SQ3")
    assert len(report.results) == 2


def test_coerce_report_handles_invalid_numbers():
    payload = {
        "subquestion_id": "SQ4",
        "results": [
            {
                "url": "https://x.com",
                "title": "T",
                "score_total": "not a number",  # bad
                "relevance": 5,
            }
        ],
    }
    # Should skip the bad result rather than crashing
    report = _coerce_report(payload, "SQ4")
    assert report.subquestion_id == "SQ4"
    # The bad result was dropped because float() raised
    assert len(report.results) == 0


def test_coerce_report_falls_back_to_provided_subquestion_id():
    # Payload missing subquestion_id → fallback parameter wins
    payload = {"results": [], "needs_more_search": False}
    report = _coerce_report(payload, "SQ_FALLBACK")
    assert report.subquestion_id == "SQ_FALLBACK"


def test_coerce_report_raises_on_non_dict():
    import pytest_compat as _

    raised = False
    try:
        _coerce_report("not a dict", "SQ?")
    except ValueError:
        raised = True
    assert raised


# ── validated_results ────────────────────────────────────────────

def test_validated_results_includes_high_and_medium():
    report = EvaluationReport(
        subquestion_id="SQ1",
        results=[
            ScoredResult(url="a", title="A", score_total=8, relevance=8, authority=8,
                         freshness=8, evidence_density=8, classification="high", reason=""),
            ScoredResult(url="b", title="B", score_total=6, relevance=6, authority=6,
                         freshness=6, evidence_density=6, classification="medium", reason=""),
            ScoredResult(url="c", title="C", score_total=3, relevance=3, authority=3,
                         freshness=3, evidence_density=3, classification="low", reason=""),
            ScoredResult(url="d", title="D", score_total=1, relevance=1, authority=1,
                         freshness=1, evidence_density=1, classification="discard", reason=""),
        ],
    )
    valid = report.validated_results()
    assert len(valid) == 2
    assert {r.url for r in valid} == {"a", "b"}


# ── _format_results_for_prompt ───────────────────────────────────

def test_format_results_for_prompt_truncates_long_snippets():
    long_snippet = "A" * 500
    results = [
        NormalizedResult(
            subquestion_id="SQ1",
            provider="ddg",
            query="q",
            title="Title",
            url="https://x.com",
            snippet=long_snippet,
            source_type="media",
        )
    ]
    text = _format_results_for_prompt(results)
    assert "..." in text
    # truncated to ~280 chars in the snippet field
    assert text.count("A") < 500


def test_format_results_for_prompt_handles_empty():
    assert _format_results_for_prompt([]) == "(no results)"


# ── Stub for raise-on-non-dict test (avoid pytest dep) ───────────

class _Sentinel:
    pass


# Inline pytest_compat helper so the test file is standalone
sys.modules.setdefault("pytest_compat", _Sentinel())


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
