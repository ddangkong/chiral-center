"""LangGraph-based report generation from simulation results.

Uses a StateGraph to orchestrate:
1. Plan report outline
2. Search graph for evidence
3. Analyze findings
4. Write sections
5. Compile final report
"""
import asyncio
import json
import uuid
from typing import TypedDict, Annotated, Optional
from datetime import datetime

from langgraph.graph import StateGraph, END

from llm.base import BaseLLMClient
from models.simulation import SimResult
from models.report import Report, ReportSection, ReportFormat
from db.neo4j_client import neo4j_client
from utils.logger import log


# ── State Definition ─────────────────────────────

class ReportState(TypedDict):
    """State that flows through the report generation graph."""
    simulation_id: str
    topic: str
    events_summary: str
    interaction_stats: str
    outline: list[dict]           # [{title, description}]
    current_section_idx: int
    sections: list[dict]          # [{title, content}]
    evidence: list[str]
    needs_more_evidence: bool
    final_markdown: str
    error: Optional[str]


# ── Node Functions ───────────────────────────────

OUTLINE_PROMPT = """You are an expert analyst writing a report about a social simulation.
All section titles and descriptions MUST be written in Korean (한국어로 작성).

Topic: {topic}
Number of agents: {num_agents}
Number of rounds: {num_rounds}
Total events: {num_events}

Simulation events summary:
{events_summary}

Interaction statistics:
{interaction_stats}

Create a report outline with 4-6 sections. Each section should cover a distinct aspect of the simulation findings.

Respond in JSON array format ONLY (titles and descriptions in Korean):
[
  {{"title": "핵심 요약", "description": "시뮬레이션 설정 및 주요 발견사항 개요"}},
  {{"title": "에이전트 역학", "description": "각 페르소나 간 상호작용과 영향력 분석"}},
  ...
]
"""

SECTION_PROMPT = """Write the "{section_title}" section for this simulation report.
IMPORTANT: Write the entire section content in Korean (한국어로 전체 내용을 작성하세요).

Topic: {topic}
Section description: {section_desc}
Evidence and data:
{evidence}

Simulation events relevant to this section:
{events}

Write a detailed, analytical section (300-500 words in Korean). Use specific examples from the simulation events.
Include observations about:
- 에이전트 행동 패턴
- 주요 전환점
- 주목할 만한 상호작용

Write in markdown format in Korean. Be analytical, not just descriptive.
"""

EVIDENCE_SEARCH_PROMPT = """Based on this report section topic, what should we search for in the knowledge graph?

Section: {section_title}
Description: {section_desc}
Topic: {topic}

Return 3-5 search queries as a JSON array:
["query1", "query2", ...]
"""


class ReportGenerator:
    """Generates analysis reports using LangGraph workflow."""

    def __init__(self, llm_client: BaseLLMClient):
        self.llm = llm_client
        self._reports: dict[str, Report] = {}
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph state graph for report generation."""
        workflow = StateGraph(ReportState)

        # Add nodes
        workflow.add_node("plan_outline", self._plan_outline)
        workflow.add_node("search_evidence", self._search_evidence)
        workflow.add_node("write_section", self._write_section)
        workflow.add_node("check_complete", self._check_complete)
        workflow.add_node("compile_report", self._compile_report)

        # Define edges
        workflow.set_entry_point("plan_outline")
        workflow.add_edge("plan_outline", "search_evidence")
        workflow.add_edge("search_evidence", "write_section")
        workflow.add_edge("write_section", "check_complete")
        workflow.add_conditional_edges(
            "check_complete",
            self._should_continue,
            {
                "continue": "search_evidence",
                "done": "compile_report",
            }
        )
        workflow.add_edge("compile_report", END)

        return workflow.compile()

    async def generate_report(
        self,
        simulation: SimResult,
        ontology_id: str,
        topic: str = "",
    ) -> Report:
        """Generate a full analysis report from simulation results."""
        log.info("report_generation_start", sim_id=simulation.id)

        effective_topic = topic or simulation.config.topic
        events_summary = self._summarize_events(simulation)
        interaction_stats = self._compute_stats(simulation)

        # Step 1: plan outline (single LLM call)
        base_state: ReportState = {
            "simulation_id": simulation.id,
            "topic": effective_topic,
            "events_summary": events_summary,
            "interaction_stats": interaction_stats,
            "outline": [],
            "current_section_idx": 0,
            "sections": [],
            "evidence": [],
            "needs_more_evidence": False,
            "final_markdown": "",
            "error": None,
        }
        outline_result = await self._plan_outline(base_state)
        outline: list[dict] = outline_result.get("outline", [])

        # Step 2: write all sections in parallel (evidence search + write happen together)
        async def _write_one(idx: int, section: dict) -> dict:
            state_for_section = {**base_state, "outline": outline, "current_section_idx": idx, "sections": []}
            ev = await self._search_evidence(state_for_section)
            state_for_section = {**state_for_section, "evidence": ev.get("evidence", [])}
            wr = await self._write_section(state_for_section)
            written = wr.get("sections", [])
            return written[0] if written else {"title": section.get("title", ""), "content": ""}

        written_sections = await asyncio.gather(*[_write_one(i, s) for i, s in enumerate(outline)])
        sections = list(written_sections)

        # Step 3: compile
        parts = [f"# 시뮬레이션 분석 보고서: {effective_topic}\n"]
        parts.append(f"*생성일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")
        parts.append("---\n")
        for s in sections:
            parts.append(f"\n## {s['title']}\n")
            parts.append(s["content"])
            parts.append("\n")
        final_markdown = "\n".join(parts)

        report = Report(
            simulation_id=simulation.id,
            title=f"시뮬레이션 분석 보고서: {effective_topic}",
            raw_markdown=final_markdown,
            sections=[
                ReportSection(title=s["title"], content=s["content"], order=i)
                for i, s in enumerate(sections)
            ],
            metadata={
                "generated_at": datetime.now().isoformat(),
                "num_events": len(simulation.events),
                "num_sections": len(sections),
            },
        )

        self._reports[report.id] = report
        log.info("report_generation_complete", report_id=report.id)
        return report

    # ── Graph Nodes ──────────────────────────────

    async def _plan_outline(self, state: ReportState) -> dict:
        """Plan the report outline."""
        events = state["events_summary"]
        stats = state["interaction_stats"]

        # Count from summary
        lines = events.split("\n")
        num_events = len([l for l in lines if l.strip()])

        prompt = OUTLINE_PROMPT.format(
            topic=state["topic"],
            num_agents="multiple",
            num_rounds="multiple",
            num_events=num_events,
            events_summary=events[:4000],
            interaction_stats=stats,
        )

        response = await self.llm.complete([
            {"role": "system", "content": "You are a simulation analyst. Respond with valid JSON only. All title and description values must be in Korean (한국어)."},
            {"role": "user", "content": prompt},
        ], temperature=0.4)

        try:
            outline = self._parse_json(response)
            if not isinstance(outline, list):
                outline = [{"title": "Analysis", "description": "General analysis"}]
        except:
            outline = [
                {"title": "Overview", "description": "Simulation overview"},
                {"title": "Agent Dynamics", "description": "Agent interaction patterns"},
                {"title": "Key Findings", "description": "Important observations"},
                {"title": "Conclusion", "description": "Summary and implications"},
            ]

        log.info("outline_planned", sections=len(outline))
        return {"outline": outline, "current_section_idx": 0}

    async def _search_evidence(self, state: ReportState) -> dict:
        """Search the knowledge graph for evidence relevant to current section."""
        idx = state["current_section_idx"]
        if idx >= len(state["outline"]):
            return {"evidence": []}

        section = state["outline"][idx]

        # Ask LLM for search queries
        try:
            response = await self.llm.complete([
                {"role": "system", "content": "Generate search queries. Respond with JSON array only."},
                {"role": "user", "content": EVIDENCE_SEARCH_PROMPT.format(
                    section_title=section["title"],
                    section_desc=section.get("description", ""),
                    topic=state["topic"],
                )},
            ], temperature=0.3)

            queries = self._parse_json(response)
            if not isinstance(queries, list):
                queries = [state["topic"]]
        except:
            queries = [state["topic"]]

        # Search Neo4j — run all queries in parallel
        async def _search_one(query: str) -> list[str]:
            try:
                records = await neo4j_client.execute(
                    """MATCH (n) WHERE
                    toLower(n.name) CONTAINS toLower($query) OR
                    toLower(n.description) CONTAINS toLower($query)
                    RETURN n.name as name, n.type as type, n.description as desc
                    LIMIT 5""",
                    {"query": query},
                )
                return [f"[{r.get('type', 'Entity')}] {r.get('name', '')}: {r.get('desc', '')}" for r in records]
            except:
                return []

        results = await asyncio.gather(*[_search_one(q) for q in queries[:5]])
        evidence = [item for sublist in results for item in sublist]

        log.info("evidence_found", section=section["title"], items=len(evidence))
        return {"evidence": evidence}

    async def _write_section(self, state: ReportState) -> dict:
        """Write the current section."""
        idx = state["current_section_idx"]
        if idx >= len(state["outline"]):
            return {}

        section = state["outline"][idx]
        evidence_text = "\n".join(state.get("evidence", [])) or "No specific graph evidence found."

        # Get relevant events for this section
        events_text = state["events_summary"][:3000]

        prompt = SECTION_PROMPT.format(
            section_title=section["title"],
            topic=state["topic"],
            section_desc=section.get("description", ""),
            evidence=evidence_text,
            events=events_text,
        )

        response = await self.llm.complete([
            {"role": "system", "content": "You are an expert analyst. Write insightful, data-driven analysis entirely in Korean (한국어로 작성)."},
            {"role": "user", "content": prompt},
        ], temperature=0.5, max_tokens=2048)

        new_sections = list(state["sections"])
        new_sections.append({
            "title": section["title"],
            "content": response,
        })

        log.info("section_written", title=section["title"], idx=idx)
        return {"sections": new_sections}

    async def _check_complete(self, state: ReportState) -> dict:
        """Check if all sections are written."""
        next_idx = state["current_section_idx"] + 1
        return {"current_section_idx": next_idx}

    def _should_continue(self, state: ReportState) -> str:
        """Decide whether to continue writing or compile."""
        if state["current_section_idx"] < len(state["outline"]):
            return "continue"
        return "done"

    async def _compile_report(self, state: ReportState) -> dict:
        """Compile all sections into final markdown."""
        parts = [f"# 시뮬레이션 분석 보고서: {state['topic']}\n"]
        parts.append(f"*생성일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")
        parts.append("---\n")

        for section in state["sections"]:
            parts.append(f"\n## {section['title']}\n")
            parts.append(section["content"])
            parts.append("\n")

        final = "\n".join(parts)
        log.info("report_compiled", length=len(final))
        return {"final_markdown": final}

    # ── Helpers ──────────────────────────────────

    def _summarize_events(self, sim: SimResult) -> str:
        """Create a text summary of simulation events."""
        lines = []
        for e in sim.events:
            if e.action_type == "skip":
                continue
            prefix = f"[Round {e.round_num}]"
            if e.action_type == "injection":
                lines.append(f"{prefix} [BREAKING] {e.content}")
            elif e.action_type == "reply":
                lines.append(f"{prefix} @{e.persona_name} replied to #{e.target_id}: {e.content}")
            elif e.action_type == "repost":
                lines.append(f"{prefix} @{e.persona_name} reposted #{e.target_id} with: {e.content}")
            else:
                lines.append(f"{prefix} @{e.persona_name}: {e.content}")
        return "\n".join(lines)

    def _compute_stats(self, sim: SimResult) -> str:
        """Compute interaction statistics."""
        stats: dict[str, dict] = {}
        for e in sim.events:
            if e.action_type == "skip":
                continue
            name = e.persona_name
            if name not in stats:
                stats[name] = {"posts": 0, "replies": 0, "reposts": 0}
            if e.action_type in stats[name]:
                stats[name][e.action_type] += 1
            else:
                stats[name]["posts"] += 1

        lines = []
        for name, s in stats.items():
            total = sum(s.values())
            lines.append(f"@{name}: {total} actions (posts={s['posts']}, replies={s['replies']}, reposts={s['reposts']})")
        return "\n".join(lines)

    def _parse_json(self, text: str) -> dict | list:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)

    def get_report(self, report_id: str) -> Optional[Report]:
        return self._reports.get(report_id)
