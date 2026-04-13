"""Research orchestrator — ties all modules into one pipeline.

Flow:
  planner → dual-provider search → normalize → dedupe → evaluate
  → (if needed, 1 follow-up round) → synthesize

Exposes a single async entrypoint `run_orchestrated_research(...)` that a
FastAPI background task can launch. Progress is reported through a
progress_callback so the SSE endpoint can stream status to the frontend.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from utils.logger import log

from core.research.search.base import (
    NormalizedResult,
    SearchProvider,
    search_with_fallback,
)
from core.research.search.providers.ddg import DDGProvider
from core.research.search.providers.openai_web import OpenAIWebProvider
from core.research.planner import plan_research, Subquestion, ResearchPlan
from core.research.normalize import normalize_results, canonical_url
from core.research.dedupe import dedupe_results
from core.research.evaluator import evaluate_subquestion, EvaluationReport
from core.research.followup_query_generator import generate_followup_queries
from core.research.synthesizer import synthesize_report


ProgressCallback = Callable[[str, dict], Awaitable[None]]
# event_type: "planning_done" | "search_step" | "evaluating" |
#             "followup" | "synthesizing" | "completed" | "failed"


@dataclass
class OrchestratorResult:
    plan: ResearchPlan | None
    all_results: list[NormalizedResult]
    evaluations: dict[str, EvaluationReport]
    report: str
    search_steps: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)

    def to_session_patch(self) -> dict:
        """Shape that research.py can merge into its session JSON."""
        return {
            "content": self.report,
            "sources": self.sources,
            "search_steps": self.search_steps,
            "plan": self.plan.to_dict() if self.plan else None,
            "evaluator_results": {
                sq_id: rep.to_dict() for sq_id, rep in self.evaluations.items()
            },
        }


async def _noop_progress(event_type: str, payload: dict) -> None:  # pragma: no cover
    pass


def _build_providers(client) -> list[SearchProvider]:
    """Build the provider list.

    OpenAI web_search is the PRIMARY provider. DDG was tested but returns
    irrelevant results for professional market research queries — disabled
    by default. Can be re-enabled with RESEARCH_DDG_SEARCH=1.
    """
    providers: list[SearchProvider] = []

    # DDG — disabled by default (too weak for market research)
    ddg_toggle = os.environ.get("RESEARCH_DDG_SEARCH", "0")
    if ddg_toggle in ("1", "true", "True", "on", "ON"):
        providers.append(DDGProvider())

    # OpenAI web_search — primary provider
    try:
        openai_toggle = os.environ.get("RESEARCH_OPENAI_WEB_SEARCH", "1")
        if openai_toggle not in ("0", "false", "False", "off", "OFF"):
            providers.append(OpenAIWebProvider(client=client))
    except Exception as exc:
        log.warning("openai_provider_init_failed", error=str(exc)[:200])
    log.info(
        "orchestrator_providers_built",
        providers=[p.name for p in providers],
        enabled=[p.name for p in providers if getattr(p, "enabled", True)],
    )
    return providers


async def _search_subquestion(
    providers: list[SearchProvider],
    subquestion: Subquestion,
    progress: ProgressCallback,
    *,
    max_results_per_query: int = 5,
) -> list[NormalizedResult]:
    """Run ALL queries for one subquestion through ALL providers concurrently."""
    all_tasks = [
        search_with_fallback(
            providers=providers,
            query=q.query,
            subquestion_id=subquestion.id,
            max_results=max_results_per_query,
        )
        for q in subquestion.queries
    ]

    collected: list[NormalizedResult] = []
    for idx, coro in enumerate(asyncio.as_completed(all_tasks), start=1):
        hits = await coro
        collected.extend(hits)
        query_text = subquestion.queries[min(idx - 1, len(subquestion.queries) - 1)].query
        await progress(
            "search_step",
            {
                "step": {
                    "subquestion_id": subquestion.id,
                    "query": query_text,
                    "status": "completed",
                    "hits": len(hits),
                }
            },
        )

    return collected


async def run_orchestrated_research(
    client,  # AsyncOpenAI
    user_query: str,
    *,
    progress_callback: Optional[ProgressCallback] = None,
    enable_followup: bool = True,
    max_results_per_query: int = 5,
) -> OrchestratorResult:
    """End-to-end orchestrated research pipeline.

    Raises on fatal failures (planner can't return valid JSON, no providers enabled).
    Individual subquestions that yield zero results degrade gracefully —
    the synthesizer is told "no validated sources" for that subquestion.
    """
    progress = progress_callback or _noop_progress
    providers = _build_providers(client)
    if not providers:
        raise RuntimeError("no search providers available")

    # ── Step 1: Planner ─────────────────────────────────────────────
    await progress("status", {"status": "planning"})
    plan = await plan_research(client, user_query)
    await progress("planning_done", {"plan": plan.to_dict()})
    log.info(
        "orchestrator_plan_ready",
        research_type=plan.research_type,
        subquestions=len(plan.subquestions),
    )

    # ── Step 2: Dual-provider search (subquestions in parallel) ─────
    await progress("status", {"status": "searching"})
    subquestion_results: dict[str, list[NormalizedResult]] = {}

    sq_tasks = [
        _search_subquestion(providers, sq, progress, max_results_per_query=max_results_per_query)
        for sq in plan.subquestions
    ]
    gathered = await asyncio.gather(*sq_tasks, return_exceptions=True)
    for sq, result in zip(plan.subquestions, gathered):
        if isinstance(result, Exception):
            log.warning("orchestrator_sq_search_failed", sq=sq.id, error=str(result)[:200])
            subquestion_results[sq.id] = []
        else:
            subquestion_results[sq.id] = result

    # Normalize + dedupe per subquestion
    await progress("status", {"status": "normalizing"})
    for sq_id, results in subquestion_results.items():
        normalize_results(results)
        subquestion_results[sq_id] = dedupe_results(results)

    total_collected = sum(len(r) for r in subquestion_results.values())
    log.info("orchestrator_search_done", total_collected=total_collected)

    # ── Step 3: Evaluator ──────────────────────────────────────────
    await progress("status", {"status": "evaluating"})
    evaluations: dict[str, EvaluationReport] = {}
    eval_tasks = [
        evaluate_subquestion(client, sq.to_dict() if hasattr(sq, "to_dict") else _sq_to_dict(sq),
                             subquestion_results[sq.id])
        for sq in plan.subquestions
    ]
    eval_results = await asyncio.gather(*eval_tasks, return_exceptions=True)
    for sq, report in zip(plan.subquestions, eval_results):
        if isinstance(report, Exception):
            log.error("orchestrator_eval_failed", sq=sq.id, error=str(report)[:200])
            evaluations[sq.id] = EvaluationReport(
                subquestion_id=sq.id,
                results=[],
                needs_more_search=False,
                gap_reason="evaluator crashed",
            )
        else:
            evaluations[sq.id] = report

    # ── Step 4: Optional follow-up round (hard cap: 1) ─────────────
    if enable_followup:
        followup_sqs = [
            (sq, evaluations[sq.id])
            for sq in plan.subquestions
            if evaluations[sq.id].needs_more_search
        ]
        if followup_sqs:
            await progress(
                "followup",
                {"count": len(followup_sqs), "reason": "evaluator flagged gaps"},
            )
            log.info("orchestrator_followup_start", count=len(followup_sqs))

            async def _followup_one(sq: Subquestion, old_report: EvaluationReport):
                original = [{"type": q.type, "query": q.query} for q in sq.queries]
                new_queries = await generate_followup_queries(
                    client, _sq_to_dict(sq), original, old_report.gap_reason
                )
                if not new_queries:
                    return sq.id, []
                extra_tasks = [
                    search_with_fallback(
                        providers=providers,
                        query=nq["query"],
                        subquestion_id=sq.id,
                        max_results=max_results_per_query,
                    )
                    for nq in new_queries
                ]
                flat: list[NormalizedResult] = []
                gathered_hits = await asyncio.gather(*extra_tasks, return_exceptions=True)
                for hits in gathered_hits:
                    if isinstance(hits, list):
                        flat.extend(hits)
                await progress(
                    "search_step",
                    {
                        "step": {
                            "subquestion_id": sq.id,
                            "query": f"[follow-up] {len(new_queries)} extra queries",
                            "status": "completed",
                            "hits": len(flat),
                        }
                    },
                )
                return sq.id, flat

            followup_results = await asyncio.gather(
                *[_followup_one(sq, rep) for sq, rep in followup_sqs],
                return_exceptions=True,
            )
            for item in followup_results:
                if isinstance(item, Exception):
                    continue
                sq_id, extra_hits = item
                if not extra_hits:
                    continue
                combined = subquestion_results.get(sq_id, []) + extra_hits
                normalize_results(combined)
                subquestion_results[sq_id] = dedupe_results(combined)

            # Re-evaluate only the subquestions that got new data
            if any(rep.needs_more_search for rep in evaluations.values()):
                re_eval_tasks = [
                    evaluate_subquestion(
                        client, _sq_to_dict(sq), subquestion_results[sq.id]
                    )
                    for sq, rep in followup_sqs
                ]
                re_eval = await asyncio.gather(*re_eval_tasks, return_exceptions=True)
                for (sq, _), report in zip(followup_sqs, re_eval):
                    if isinstance(report, EvaluationReport):
                        evaluations[sq.id] = report

    # ── Step 4b: Best-effort fallback ────────────────────────────────
    # If ALL subquestions ended up with 0 validated (high/medium) results even
    # after follow-up, the synthesizer would have nothing to work with. In this
    # case, promote "low" results to "medium" so the synthesizer can still
    # produce a useful (if lower-quality) report instead of an empty one.
    total_validated = sum(
        len(rep.validated_results()) for rep in evaluations.values()
    )
    if total_validated == 0:
        log.warning(
            "orchestrator_best_effort_fallback",
            reason="all evaluations returned 0 high/medium results — promoting low→medium",
        )
        for rep in evaluations.values():
            for scored in rep.results:
                if scored.classification == "low":
                    scored.classification = "medium"
                    scored.reason = f"[best-effort promoted] {scored.reason}"

    # ── Step 5: Synthesizer ────────────────────────────────────────
    await progress("status", {"status": "synthesizing"})

    # Build a url → NormalizedResult map for the synthesizer
    results_by_url: dict[str, NormalizedResult] = {}
    flat_results: list[NormalizedResult] = []
    for sq_id, results in subquestion_results.items():
        for r in results:
            key = canonical_url(r.url) or r.url
            if key and key not in results_by_url:
                results_by_url[key] = r
            flat_results.append(r)

    report_md = await synthesize_report(
        client,
        plan,
        evaluations,
        results_by_url,
        user_query=user_query,
    )

    # ── Step 6: Package search_steps and sources for the session JSON ──
    search_steps: list[dict] = []
    for sq in plan.subquestions:
        for q in sq.queries:
            search_steps.append({
                "action_type": "search",
                "query": q.query,
                "subquestion_id": sq.id,
                "status": "completed",
            })

    sources: list[dict] = []
    seen_source_urls: set[str] = set()
    for sq_id, report in evaluations.items():
        for scored in report.validated_results():
            key = canonical_url(scored.url) or scored.url
            if not key or key in seen_source_urls:
                continue
            seen_source_urls.add(key)
            raw = results_by_url.get(key)
            sources.append({
                "url": scored.url,
                "title": scored.title,
                "source_type": raw.source_type if raw else "unknown",
                "classification": scored.classification,
                "subquestion_id": sq_id,
            })

    await progress("status", {"status": "completed"})
    log.info(
        "orchestrator_complete",
        subquestion_count=len(plan.subquestions),
        total_sources=len(sources),
        report_len=len(report_md),
    )

    return OrchestratorResult(
        plan=plan,
        all_results=flat_results,
        evaluations=evaluations,
        report=report_md,
        search_steps=search_steps,
        sources=sources,
    )


def _sq_to_dict(sq: Subquestion) -> dict:
    """Subquestion dataclass → dict form expected by evaluator."""
    return {
        "id": sq.id,
        "question": sq.question,
        "priority": sq.priority,
        "why_it_matters": sq.why_it_matters,
        "strong_evidence_definition": sq.strong_evidence_definition,
        "queries": [{"type": q.type, "query": q.query} for q in sq.queries],
        "blind_spots": sq.blind_spots,
        "stop_condition": sq.stop_condition,
    }
