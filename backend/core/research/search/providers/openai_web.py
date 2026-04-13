"""OpenAI Responses API web_search tool — second search provider.

This wraps the same `client.responses.create(...)` call that the existing
o3/o4 deep research uses, but in *blocking* mode (background=False) and with
a tight system prompt that forces a single-pass search and structured JSON
output. The orchestrator then merges these results with DDG hits.

Toggle: env var RESEARCH_OPENAI_WEB_SEARCH=1 (default) | =0 (disabled).
"""
from __future__ import annotations

import json
import os
import re

from utils.logger import log
from core.research.search.base import NormalizedResult
from core.research.normalize import classify_source_type


_DEFAULT_MODEL = os.environ.get("RESEARCH_OPENAI_WEB_MODEL", "gpt-4o-mini")


_SEARCH_INSTRUCTIONS = """You are a focused web research assistant.

Goal: For the user query below, run web searches via your web_search tool and
return a JSON array of the most relevant results. Do NOT write any prose
analysis — just return raw search hits as JSON.

Output format (strict — no additional text):
{
  "results": [
    {
      "title": "...",
      "url": "https://...",
      "snippet": "1-2 sentence summary of the page content",
      "published_at": "YYYY-MM-DD or null if unknown"
    }
  ]
}

Rules:
- Return at most {max_results} results.
- Each url must be a real, full https URL from the search tool output.
- snippet must be a faithful summary of the page content the search tool returned.
- Do not invent or fabricate URLs. If you can't find anything, return {"results": []}.
- Respond with ONLY the JSON object — no markdown, no explanation.
"""


def _extract_json_block(text: str) -> dict | None:
    """Best-effort JSON extraction from an LLM response."""
    if not text:
        return None
    text = text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract first {...} block
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


class OpenAIWebProvider:
    """Search provider backed by OpenAI Responses API + web_search tool.

    Holds a reference to an `AsyncOpenAI` client; doesn't create one itself.
    The orchestrator instantiates the client once with the user's API key
    and passes it in.
    """

    name = "openai_web"

    def __init__(
        self,
        client,  # AsyncOpenAI
        *,
        model: str = _DEFAULT_MODEL,
        enabled: bool | None = None,
    ) -> None:
        self.client = client
        self.model = model
        # Env var override allows operator to disable globally without code change.
        env_toggle = os.environ.get("RESEARCH_OPENAI_WEB_SEARCH", "1")
        env_enabled = env_toggle not in ("0", "false", "False", "off", "OFF")
        # Caller can force-disable; otherwise honor env var
        self.enabled = env_enabled if enabled is None else enabled

    async def search(
        self,
        query: str,
        subquestion_id: str,
        max_results: int = 5,
    ) -> list[NormalizedResult]:
        if not self.enabled or self.client is None:
            return []

        instructions = _SEARCH_INSTRUCTIONS.format(max_results=max_results)
        try:
            response = await self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "developer", "content": [{"type": "input_text", "text": instructions}]},
                    {"role": "user", "content": [{"type": "input_text", "text": query}]},
                ],
                tools=[{"type": "web_search_preview"}],
                background=False,
            )
        except Exception as exc:
            log.warning(
                "openai_web_call_failed",
                query=query,
                error=str(exc)[:200],
            )
            return []

        # The Responses API returns `output_text` for the final assistant message.
        text = getattr(response, "output_text", None) or ""
        parsed = _extract_json_block(text)

        # Fallback: walk the message annotations directly if JSON parse failed.
        results: list[NormalizedResult] = []
        if parsed and isinstance(parsed.get("results"), list):
            for item in parsed["results"][:max_results]:
                url = (item.get("url") or "").strip()
                if not url:
                    continue
                results.append(
                    NormalizedResult(
                        subquestion_id=subquestion_id,
                        provider=self.name,
                        query=query,
                        title=(item.get("title") or "").strip(),
                        url=url,
                        snippet=(item.get("snippet") or "").strip(),
                        published_at=item.get("published_at"),
                        source_type=classify_source_type(url),
                        raw=item,
                    )
                )

        if not results:
            # Fallback 1: Walk message annotations (same pattern as research.py)
            try:
                for item in (response.output or []):
                    if getattr(item, "type", "") != "message":
                        continue
                    content_list = getattr(item, "content", []) or []
                    for content_block in content_list:
                        annotations = getattr(content_block, "annotations", []) or []
                        for ann in annotations[:max_results]:
                            url = (getattr(ann, "url", "") or "").strip()
                            if not url:
                                continue
                            results.append(
                                NormalizedResult(
                                    subquestion_id=subquestion_id,
                                    provider=self.name,
                                    query=query,
                                    title=(getattr(ann, "title", "") or "").strip(),
                                    url=url,
                                    snippet="",
                                    published_at=None,
                                    source_type=classify_source_type(url),
                                    raw={"annotation": True},
                                )
                            )
            except Exception as exc:
                log.warning("openai_web_annotation_walk_failed", error=str(exc)[:200])

        if not results:
            # Fallback 2: Extract URLs from the output_text itself using regex
            # (when the model returns prose with inline URLs instead of JSON)
            try:
                import re as _re
                url_pattern = _re.compile(r'https?://[^\s\)\]"\'<>]+')
                seen_fb = set()
                for match in url_pattern.finditer(text):
                    url = match.group(0).rstrip(".,;:)")
                    if url in seen_fb:
                        continue
                    seen_fb.add(url)
                    results.append(
                        NormalizedResult(
                            subquestion_id=subquestion_id,
                            provider=self.name,
                            query=query,
                            title="",
                            url=url,
                            snippet="",
                            published_at=None,
                            source_type=classify_source_type(url),
                            raw={"extracted_from_text": True},
                        )
                    )
                    if len(results) >= max_results:
                        break
            except Exception as exc:
                log.warning("openai_web_url_extraction_failed", error=str(exc)[:200])

        log.info(
            "openai_web_search_complete",
            subquestion=subquestion_id,
            query=query,
            hits=len(results),
        )
        return results
