"""In-memory task tracking for long-running API jobs."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any
import uuid

from pydantic import BaseModel, Field


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: str
    status: str = "queued"
    progress: int = 0
    message: str = "Queued"
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)
    result: dict[str, Any] | None = None
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = Lock()

    def create_task(self, kind: str, meta: dict[str, Any] | None = None) -> TaskRecord:
        task = TaskRecord(kind=kind, meta=meta or {})
        with self._lock:
            self._tasks[task.id] = task
        return task

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return task.model_copy(deep=True) if task else None

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> TaskRecord | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            updates: dict[str, Any] = {"updated_at": _utc_now_iso()}
            if status is not None:
                updates["status"] = status
            if progress is not None:
                updates["progress"] = max(0, min(100, int(progress)))
            if message is not None:
                updates["message"] = message
            if result is not None:
                updates["result"] = result
            if error is not None:
                updates["error"] = error
            if meta is not None:
                updates["meta"] = {**task.meta, **meta}

            updated = task.model_copy(update=updates)
            self._tasks[task_id] = updated
            return updated.model_copy(deep=True)

    def complete_task(
        self,
        task_id: str,
        *,
        message: str = "Completed",
        result: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> TaskRecord | None:
        return self.update_task(
            task_id,
            status="completed",
            progress=100,
            message=message,
            result=result,
            error=None,
            meta=meta,
        )

    def fail_task(self, task_id: str, error: str, *, message: str = "Failed") -> TaskRecord | None:
        return self.update_task(
            task_id,
            status="failed",
            message=message,
            error=error,
        )


task_manager = TaskManager()
