"""Search provider abstraction for the research orchestrator."""
from core.research.search.base import (
    NormalizedResult,
    SearchProvider,
    search_with_fallback,
)

__all__ = ["NormalizedResult", "SearchProvider", "search_with_fallback"]
