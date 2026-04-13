"""Tests for search.base.search_with_fallback — provider failure handling."""
import sys
import pathlib
import asyncio

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from core.research.search.base import (
    NormalizedResult,
    search_with_fallback,
)


# ── Fake providers for testing ──────────────────────────────────

class _FakeOK:
    name = "ok_provider"
    enabled = True

    def __init__(self, hits: int = 3):
        self.hits = hits

    async def search(self, query, subquestion_id, max_results=5):
        return [
            NormalizedResult(
                subquestion_id=subquestion_id,
                provider=self.name,
                query=query,
                title=f"OK result {i}",
                url=f"https://ok.com/r{i}",
                snippet="ok",
            )
            for i in range(self.hits)
        ]


class _FakeRaises:
    name = "broken_provider"
    enabled = True

    async def search(self, query, subquestion_id, max_results=5):
        raise RuntimeError("upstream API down")


class _FakeTimesOut:
    name = "slow_provider"
    enabled = True

    async def search(self, query, subquestion_id, max_results=5):
        await asyncio.sleep(10)  # longer than fallback timeout
        return []


class _FakeDisabled:
    name = "disabled_provider"
    enabled = False

    async def search(self, query, subquestion_id, max_results=5):
        raise RuntimeError("should never be called")


# ── Tests ──────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def test_all_providers_succeed():
    providers = [_FakeOK(hits=3), _FakeOK(hits=2)]
    results = _run(search_with_fallback(providers, "q", "SQ1"))
    assert len(results) == 5


def test_one_provider_raises_others_succeed():
    providers = [_FakeOK(hits=4), _FakeRaises()]
    results = _run(search_with_fallback(providers, "q", "SQ1"))
    assert len(results) == 4
    assert all(r.provider == "ok_provider" for r in results)


def test_all_providers_fail_returns_empty():
    providers = [_FakeRaises(), _FakeRaises()]
    results = _run(search_with_fallback(providers, "q", "SQ1"))
    assert results == []


def test_disabled_providers_are_skipped():
    providers = [_FakeOK(hits=2), _FakeDisabled()]
    results = _run(search_with_fallback(providers, "q", "SQ1"))
    assert len(results) == 2
    assert all(r.provider == "ok_provider" for r in results)


def test_no_enabled_providers_returns_empty():
    providers = [_FakeDisabled(), _FakeDisabled()]
    results = _run(search_with_fallback(providers, "q", "SQ1"))
    assert results == []


def test_timeout_does_not_block_other_providers():
    providers = [_FakeOK(hits=3), _FakeTimesOut()]
    results = _run(search_with_fallback(providers, "q", "SQ1", timeout_per_provider=0.5))
    # Should get OK results despite the slow one timing out
    assert len(results) == 3
    assert all(r.provider == "ok_provider" for r in results)


def test_results_include_subquestion_and_query():
    providers = [_FakeOK(hits=1)]
    results = _run(search_with_fallback(providers, "test query", "SQ7"))
    assert len(results) == 1
    assert results[0].subquestion_id == "SQ7"
    assert results[0].query == "test query"


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
