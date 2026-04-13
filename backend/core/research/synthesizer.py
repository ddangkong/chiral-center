"""Synthesizer — final markdown report from validated evidence."""
from __future__ import annotations

import json
import os

from utils.logger import log
from core.research.prompts.synthesizer_prompt import SYNTHESIZER_SYSTEM_PROMPT
from core.research.planner import ResearchPlan
from core.research.evaluator import EvaluationReport
from core.research.search.base import NormalizedResult


_SYNTHESIZER_MODEL = os.environ.get("RESEARCH_SYNTHESIZER_MODEL", "gpt-4o-mini")


def _build_payload(
    plan: ResearchPlan,
    evaluations: dict[str, EvaluationReport],
    results_by_url: dict[str, NormalizedResult],
) -> dict:
    """Construct a compact JSON payload for the synthesizer LLM."""
    sq_sections = []
    for sq in plan.subquestions:
        evaluation = evaluations.get(sq.id)
        if not evaluation:
            sq_sections.append({
                "id": sq.id,
                "question": sq.question,
                "validated_results": [],
            })
            continue

        validated = evaluation.validated_results()
        validated_payload = []
        for scored in validated:
            raw = results_by_url.get(scored.url)
            validated_payload.append({
                "url": scored.url,
                "title": scored.title,
                "source_type": raw.source_type if raw else "unknown",
                "published_at": raw.published_at if raw else None,
                "snippet": (raw.snippet if raw else "")[:800],
                "classification": scored.classification,
                "score_total": scored.score_total,
                "contradiction_flag": scored.contradiction_flag,
                "reason": scored.reason,
            })
        sq_sections.append({
            "id": sq.id,
            "question": sq.question,
            "why_it_matters": sq.why_it_matters,
            "validated_results": validated_payload,
            "gap_reason": evaluation.gap_reason,
        })

    return {
        "research_type": plan.research_type,
        "decision_goal": plan.decision_goal,
        "global_risks": plan.global_risks,
        "subquestions": sq_sections,
    }


async def synthesize_report(
    client,  # AsyncOpenAI
    plan: ResearchPlan,
    evaluations: dict[str, EvaluationReport],
    results_by_url: dict[str, NormalizedResult],
    *,
    user_query: str,
    model: str = _SYNTHESIZER_MODEL,
    temperature: float = 0.4,
) -> str:
    """Generate the final markdown report. Returns a single markdown string."""
    payload = _build_payload(plan, evaluations, results_by_url)

    total_validated = sum(
        len(sec.get("validated_results", [])) for sec in payload["subquestions"]
    )
    log.info(
        "synthesizer_start",
        model=model,
        subquestion_count=len(payload["subquestions"]),
        total_validated_sources=total_validated,
    )

    user_message = (
        f"## Original user query\n{user_query}\n\n"
        f"## Research plan + validated evidence (JSON)\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        f"Generate the final markdown report following the system instructions. "
        f"Respond with the markdown only — no preface."
    )

    response = await client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=6000,
        messages=[
            {"role": "system", "content": SYNTHESIZER_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )
    report = response.choices[0].message.content or ""
    log.info("synthesizer_done", report_len=len(report))
    return report
