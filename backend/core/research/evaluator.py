"""Evaluator — scores deduped results per subquestion using GPT.

For each subquestion the orchestrator calls `evaluate_subquestion(plan_sq, results)`
and gets back an `EvaluationReport` matching the spec schema 1:1.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from utils.logger import log
from core.research.prompts.evaluator_prompt import EVALUATOR_SYSTEM_PROMPT
from core.research.search.base import NormalizedResult


_EVALUATOR_MODEL = os.environ.get("RESEARCH_EVALUATOR_MODEL", "gpt-4o-mini")


@dataclass
class ScoredResult:
    url: str
    title: str
    score_total: float
    relevance: float
    authority: float
    freshness: float
    evidence_density: float
    classification: str  # high|medium|low|discard
    reason: str
    contradiction_flag: bool = False

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "score_total": self.score_total,
            "relevance": self.relevance,
            "authority": self.authority,
            "freshness": self.freshness,
            "evidence_density": self.evidence_density,
            "classification": self.classification,
            "reason": self.reason,
            "contradiction_flag": self.contradiction_flag,
        }


@dataclass
class EvaluationReport:
    subquestion_id: str
    results: list[ScoredResult] = field(default_factory=list)
    needs_more_search: bool = False
    gap_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "subquestion_id": self.subquestion_id,
            "results": [r.to_dict() for r in self.results],
            "needs_more_search": self.needs_more_search,
            "gap_reason": self.gap_reason,
        }

    def validated_results(self) -> list[ScoredResult]:
        """Results worth feeding into the synthesizer (high or medium)."""
        return [r for r in self.results if r.classification in ("high", "medium")]


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


def _coerce_report(data: dict, subquestion_id: str) -> EvaluationReport:
    if not isinstance(data, dict):
        raise ValueError("evaluator returned non-object")

    raw_results = data.get("results") or []
    scored: list[ScoredResult] = []
    for r in raw_results:
        if not isinstance(r, dict):
            continue
        try:
            scored.append(
                ScoredResult(
                    url=str(r.get("url") or ""),
                    title=str(r.get("title") or ""),
                    score_total=float(r.get("score_total") or 0),
                    relevance=float(r.get("relevance") or 0),
                    authority=float(r.get("authority") or 0),
                    freshness=float(r.get("freshness") or 0),
                    evidence_density=float(r.get("evidence_density") or 0),
                    classification=str(r.get("classification") or "low"),
                    reason=str(r.get("reason") or ""),
                    contradiction_flag=bool(r.get("contradiction_flag") or False),
                )
            )
        except (TypeError, ValueError):
            continue

    return EvaluationReport(
        subquestion_id=str(data.get("subquestion_id") or subquestion_id),
        results=scored,
        needs_more_search=bool(data.get("needs_more_search") or False),
        gap_reason=str(data.get("gap_reason") or ""),
    )


def _format_results_for_prompt(results: list[NormalizedResult]) -> str:
    """Compact text representation for the evaluator LLM."""
    lines = []
    for i, r in enumerate(results, start=1):
        snippet = (r.snippet or "").strip().replace("\n", " ")
        if len(snippet) > 280:
            snippet = snippet[:280] + "..."
        lines.append(
            f"[{i}] title: {r.title.strip()}\n"
            f"    url: {r.url}\n"
            f"    source_type: {r.source_type}\n"
            f"    published_at: {r.published_at or 'unknown'}\n"
            f"    snippet: {snippet}"
        )
    return "\n\n".join(lines) if lines else "(no results)"


async def evaluate_subquestion(
    client,  # AsyncOpenAI
    subquestion: dict,
    results: list[NormalizedResult],
    *,
    model: str = _EVALUATOR_MODEL,
    temperature: float = 0.2,
) -> EvaluationReport:
    """Score and classify the results for one subquestion.

    `subquestion` is the dict form (from `Subquestion.to_dict()`) so this module
    doesn't depend on the planner dataclass shape.
    """
    sq_id = subquestion.get("id") or "SQ?"
    if not results:
        log.warning("evaluator_no_results", subquestion=sq_id)
        return EvaluationReport(
            subquestion_id=sq_id,
            results=[],
            needs_more_search=True,
            gap_reason="No search results were collected.",
        )

    log.info("evaluator_start", subquestion=sq_id, result_count=len(results), model=model)

    user_payload = {
        "subquestion": {
            "id": sq_id,
            "question": subquestion.get("question", ""),
            "strong_evidence_definition": subquestion.get("strong_evidence_definition", []),
            "stop_condition": subquestion.get("stop_condition", ""),
        },
        "results_text": _format_results_for_prompt(results),
    }

    user_message = (
        f"## Subquestion\n"
        f"id: {user_payload['subquestion']['id']}\n"
        f"question: {user_payload['subquestion']['question']}\n"
        f"strong_evidence_definition: {json.dumps(user_payload['subquestion']['strong_evidence_definition'], ensure_ascii=False)}\n"
        f"stop_condition: {user_payload['subquestion']['stop_condition']}\n\n"
        f"## Results to evaluate\n"
        f"{user_payload['results_text']}\n\n"
        f"Score every result and respond with the JSON object per the system instructions."
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=3000,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": EVALUATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
    except Exception as exc:
        log.error("evaluator_call_failed", subquestion=sq_id, error=str(exc)[:200])
        # Fail-open: treat all results as medium quality so synthesis can continue
        return EvaluationReport(
            subquestion_id=sq_id,
            results=[
                ScoredResult(
                    url=r.url,
                    title=r.title,
                    score_total=5.0,
                    relevance=5.0,
                    authority=5.0,
                    freshness=5.0,
                    evidence_density=5.0,
                    classification="medium",
                    reason="evaluator unavailable, default-passed",
                )
                for r in results[:20]
            ],
            needs_more_search=False,
            gap_reason="",
        )

    text = response.choices[0].message.content or ""
    parsed = _extract_json(text)
    if not parsed:
        log.error("evaluator_json_parse_failed", subquestion=sq_id, raw_preview=text[:300])
        raise ValueError(f"evaluator returned non-JSON for {sq_id}")

    report = _coerce_report(parsed, sq_id)
    log.info(
        "evaluator_done",
        subquestion=sq_id,
        scored=len(report.results),
        high=sum(1 for r in report.results if r.classification == "high"),
        medium=sum(1 for r in report.results if r.classification == "medium"),
        contradictions=sum(1 for r in report.results if r.contradiction_flag),
        needs_more_search=report.needs_more_search,
    )
    return report
