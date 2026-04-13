"""Task status routes."""
from fastapi import APIRouter, HTTPException

from core.task_manager import task_manager

router = APIRouter()


@router.get("/{task_id}")
async def get_task(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task.model_dump()
