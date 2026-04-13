"""Report generation and export routes."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from typing import Optional

from llm.factory import get_llm_client
from core.report_generator import ReportGenerator

router = APIRouter()

_generators: dict[str, ReportGenerator] = {}


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: Optional[str] = None


class GenerateRequest(BaseModel):
    simulation_id: str
    ontology_id: str = ""
    topic: str = ""
    llm: LLMConfig = LLMConfig()


@router.post("/generate")
async def generate_report(req: GenerateRequest):
    """Generate analysis report from simulation."""
    if not req.llm.api_key:
        raise HTTPException(400, "API key is required")

    # Find simulation result — check memory first, then disk
    from api.routes.simulation import _engines, _load_sim

    sim_result = None
    for engine in _engines.values():
        sim = engine.get_simulation(req.simulation_id)
        if sim:
            sim_result = sim
            break

    if not sim_result:
        sim_result = _load_sim(req.simulation_id)

    if not sim_result:
        raise HTTPException(404, "Simulation not found. Please re-run the simulation.")

    llm = get_llm_client(
        provider=req.llm.provider,
        api_key=req.llm.api_key,
        model=req.llm.model,
        base_url=req.llm.base_url,
        feature="report",
    )

    generator = ReportGenerator(llm)
    report = await generator.generate_report(
        simulation=sim_result,
        ontology_id=req.ontology_id,
        topic=req.topic,
    )

    _generators[report.id] = generator

    return {
        "id": report.id,
        "title": report.title,
        "sections": [
            {"title": s.title, "content": s.content, "order": s.order} for s in report.sections
        ],
        "markdown": report.raw_markdown,
    }


@router.get("/{report_id}")
async def get_report(report_id: str):
    """Get report by ID."""
    for gen in _generators.values():
        report = gen.get_report(report_id)
        if report:
            return {
                "id": report.id,
                "title": report.title,
                "markdown": report.raw_markdown,
                "sections": [
                    {"title": s.title, "content": s.content, "order": s.order}
                    for s in report.sections
                ],
            }
    raise HTTPException(404, "Report not found")


@router.get("/{report_id}/export")
async def export_report(report_id: str, format: str = "markdown"):
    """Export report in specified format."""
    report = None
    for gen in _generators.values():
        report = gen.get_report(report_id)
        if report:
            break

    if not report:
        raise HTTPException(404, "Report not found")

    if format == "markdown":
        return PlainTextResponse(
            content=report.raw_markdown,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f"attachment; filename=report_{report_id[:8]}.md"
            },
        )
    elif format == "json":
        return {
            "id": report.id,
            "title": report.title,
            "sections": [
                {"title": s.title, "content": s.content} for s in report.sections
            ],
            "metadata": report.metadata,
        }
    else:
        raise HTTPException(400, f"Unsupported format: {format}")
