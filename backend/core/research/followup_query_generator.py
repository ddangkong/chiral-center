"""Follow-up query generator — turns evaluator gap_reason into 2-3 fresh queries.

Called once per subquestion when `evaluator.needs_more_search == True`. The
generated queries go back through the dual-search → normalize → dedupe → eval
pipeline one more time. Hard cap at 1 follow-up round (orchestrator enforces).
"""
from __future__ import annotations

import json
import os
import re

from utils.logger import log


_FOLLOWUP_MODEL = os.environ.get("RESEARCH_FOLLOWUP_MODEL", "gpt-4o-mini")


_FOLLOWUP_SYSTEM_PROMPT = """You are a research follow-up query specialist.

Given:
- A research subquestion
- The original queries that were already tried
- An explicit gap_reason from the evaluator (what's missing)

Your job: produce 2 to 3 NEW search queries that would specifically close the gap.

Output: SINGLE JSON object — no prose, no markdown fences:
{
  "queries": [
    {"type": "...", "query": "..."},
    {"type": "...", "query": "..."}
  ]
}

Rules:
1. New queries must NOT repeat the original ones — vary terminology, scope, language, or angle.
2. Match the subquestion's language. Korean question → Korean queries. English → English. Mix only when proper nouns require it.
3. Choose query type from: broad_discovery, authority_focused, recent_update, quantitative_evidence, validation_check, contrarian_evidence.
4. If the gap_reason mentions a specific data type ("market size figure", "regulatory ruling", "competitor pricing"), at least one query must explicitly target that type.
5. If the gap_reason mentions contradictions, at least one query must be `contrarian_evidence` style — looking for the opposing view.
6. Do not add commentary outside the JSON.

The very first character of your response must be `{`.
"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


def _extract_json(text: str) -> dict | None:
    text = _strip_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


async def generate_followup_queries(
    client,  # AsyncOpenAI
    subquestion: dict,
    original_queries: list[dict],
    gap_reason: str,
    *,
    model: str = _FOLLOWUP_MODEL,
    temperature: float = 0.5,
) -> list[dict]:
    """Returns a list of {type, query} dicts (2-3 items). Empty list on failure."""
    sq_id = subquestion.get("id") or "SQ?"
    if not gap_reason.strip():
        return []

    log.info(
        "followup_generator_start",
        subquestion=sq_id,
        original_query_count=len(original_queries),
        gap_reason_preview=gap_reason[:120],
    )

    user_message = (
        f"## Subquestion\n"
        f"id: {sq_id}\n"
        f"question: {subquestion.get('question', '')}\n\n"
        f"## Original queries already tried\n"
        f"{json.dumps(original_queries, ensure_ascii=False, indent=2)}\n\n"
        f"## Gap reason from evaluator\n"
        f"{gap_reason}\n\n"
        f"Generate 2-3 new queries that close this gap. Respond with JSON only."
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=600,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _FOLLOWUP_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
    except Exception as exc:
        log.warning("followup_generator_call_failed", subquestion=sq_id, error=str(exc)[:200])
        return []

    text = response.choices[0].message.content or ""
    parsed = _extract_json(text)
    if not parsed or not isinstance(parsed.get("queries"), list):
        log.warning("followup_generator_parse_failed", subquestion=sq_id)
        return []

    out: list[dict] = []
    for q in parsed["queries"][:3]:
        if not isinstance(q, dict):
            continue
        query_text = (q.get("query") or "").strip()
        if not query_text:
            continue
        out.append(
            {
                "type": str(q.get("type") or "broad_discovery"),
                "query": query_text,
            }
        )

    log.info("followup_generator_done", subquestion=sq_id, generated=len(out))
    return out
