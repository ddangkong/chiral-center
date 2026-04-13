"""Planner — converts the user's research query into a structured ResearchPlan.

Calls GPT (chat completions for structured output reliability) with the
PLANNER_SYSTEM_PROMPT and validates the JSON shape before returning.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from utils.logger import log
from core.research.prompts.planner_prompt import PLANNER_SYSTEM_PROMPT


_PLANNER_MODEL = os.environ.get("RESEARCH_PLANNER_MODEL", "gpt-4o-mini")


@dataclass
class SearchQuery:
    type: str  # broad_discovery | authority_focused | recent_update | quantitative_evidence | validation_check
    query: str


@dataclass
class Subquestion:
    id: str
    question: str
    priority: int
    why_it_matters: str
    strong_evidence_definition: list[str]
    queries: list[SearchQuery]
    blind_spots: list[str]
    stop_condition: str


@dataclass
class ResearchPlan:
    research_type: str
    decision_goal: str
    subquestions: list[Subquestion]
    global_risks: list[str] = field(default_factory=list)
    synthesis_ready_when: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "research_type": self.research_type,
            "decision_goal": self.decision_goal,
            "subquestions": [
                {
                    "id": sq.id,
                    "question": sq.question,
                    "priority": sq.priority,
                    "why_it_matters": sq.why_it_matters,
                    "strong_evidence_definition": sq.strong_evidence_definition,
                    "queries": [{"type": q.type, "query": q.query} for q in sq.queries],
                    "blind_spots": sq.blind_spots,
                    "stop_condition": sq.stop_condition,
                }
                for sq in self.subquestions
            ],
            "global_risks": self.global_risks,
            "synthesis_ready_when": self.synthesis_ready_when,
        }


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
    # Fallback: first {...} block
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _coerce_plan(data: dict) -> ResearchPlan:
    """Validate and coerce the planner JSON into a ResearchPlan dataclass."""
    if not isinstance(data, dict):
        raise ValueError("planner returned non-object")

    sqs_raw = data.get("subquestions") or []
    if not isinstance(sqs_raw, list) or not sqs_raw:
        raise ValueError("planner returned no subquestions")

    subquestions: list[Subquestion] = []
    for idx, sq in enumerate(sqs_raw, start=1):
        if not isinstance(sq, dict):
            continue
        queries_raw = sq.get("queries") or []
        queries = [
            SearchQuery(
                type=str(q.get("type") or "broad_discovery"),
                query=str(q.get("query") or "").strip(),
            )
            for q in queries_raw
            if isinstance(q, dict) and (q.get("query") or "").strip()
        ]
        if not queries:
            # Skip empty subquestions
            continue
        subquestions.append(
            Subquestion(
                id=str(sq.get("id") or f"SQ{idx}"),
                question=str(sq.get("question") or "").strip(),
                priority=int(sq.get("priority") or idx),
                why_it_matters=str(sq.get("why_it_matters") or "").strip(),
                strong_evidence_definition=[
                    str(x) for x in (sq.get("strong_evidence_definition") or []) if x
                ],
                queries=queries,
                blind_spots=[str(x) for x in (sq.get("blind_spots") or []) if x],
                stop_condition=str(sq.get("stop_condition") or "").strip(),
            )
        )

    if not subquestions:
        raise ValueError("planner produced no usable subquestions after validation")

    return ResearchPlan(
        research_type=str(data.get("research_type") or "other"),
        decision_goal=str(data.get("decision_goal") or "").strip(),
        subquestions=subquestions,
        global_risks=[str(x) for x in (data.get("global_risks") or []) if x],
        synthesis_ready_when=[str(x) for x in (data.get("synthesis_ready_when") or []) if x],
        raw=data,
    )


async def plan_research(
    client,  # AsyncOpenAI
    user_query: str,
    *,
    model: str = _PLANNER_MODEL,
    temperature: float = 0.3,
) -> ResearchPlan:
    """Run the planner step. Returns a validated ResearchPlan or raises ValueError."""
    log.info("planner_start", model=model, query_len=len(user_query))

    response = await client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=3500,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_query},
        ],
    )
    text = response.choices[0].message.content or ""
    data = _extract_json(text)
    if not data:
        log.error("planner_json_parse_failed", raw_preview=text[:300])
        raise ValueError("planner returned non-JSON output")

    plan = _coerce_plan(data)
    log.info(
        "planner_done",
        research_type=plan.research_type,
        subquestion_count=len(plan.subquestions),
        total_queries=sum(len(sq.queries) for sq in plan.subquestions),
    )
    return plan
