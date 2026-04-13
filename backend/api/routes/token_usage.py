"""Token usage tracking API routes."""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from core.token_tracker import token_tracker

router = APIRouter()


class UsageQuery(BaseModel):
    days: int | None = None        # 최근 N일
    date_from: str | None = None   # "2024-01-01"
    date_to: str | None = None     # "2024-12-31"


@router.get("/summary")
async def get_usage_summary(days: int | None = None, date_from: str | None = None, date_to: str | None = None):
    """기간별 토큰 사용량 요약."""
    return token_tracker.get_summary(days=days, date_from=date_from, date_to=date_to)


@router.get("/recent")
async def get_recent_usage(limit: int = 50):
    """최근 토큰 사용 기록."""
    return {"records": token_tracker.get_recent(limit=limit)}


@router.post("/flush")
async def flush_usage():
    """디스크에 즉시 저장."""
    token_tracker.flush()
    return {"flushed": True}


@router.delete("/clear")
async def clear_usage():
    """모든 사용 기록 삭제."""
    token_tracker.clear()
    return {"cleared": True}
