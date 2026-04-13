"""Main API router."""
from fastapi import APIRouter

from api.routes.documents import router as documents_router
from api.routes.ontology import router as ontology_router
from api.routes.graph import router as graph_router
from api.routes.simulation import router as simulation_router
from api.routes.report import router as report_router
from api.routes.database import router as database_router
from api.routes.persona_crawler import router as persona_crawler_router
from api.routes.token_usage import router as token_usage_router
from api.routes.tasks import router as tasks_router
from api.routes.research import router as research_router


router = APIRouter(prefix="/api")

router.include_router(documents_router, prefix="/documents", tags=["documents"])
router.include_router(ontology_router, prefix="/ontology", tags=["ontology"])
router.include_router(graph_router, prefix="/graph", tags=["graph"])
router.include_router(simulation_router, prefix="/simulation", tags=["simulation"])
router.include_router(report_router, prefix="/report", tags=["report"])
router.include_router(database_router, prefix="/db", tags=["database"])
router.include_router(persona_crawler_router, prefix="/persona", tags=["persona"])
router.include_router(token_usage_router, prefix="/tokens", tags=["tokens"])
router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
router.include_router(research_router, prefix="/research", tags=["research"])
