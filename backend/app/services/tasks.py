from __future__ import annotations

from app.services.provenance import actor_snapshot

from collections.abc import Callable
from datetime import datetime
import logging
import time
from threading import Lock
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.timezones import shanghai_now
from app.models import Task

logger = logging.getLogger(__name__)

_progress_lock = Lock()
_last_progress_at: dict[str, float] = {}
_PROGRESS_INTERVAL_SECONDS = 1.0


def create_task(db: Session, kind: str, message: str | None = None, workspace_id: int | None = None, *, actor_id: int | None = None) -> Task:
    task = Task(created_by=actor_id, actor_name=actor_snapshot(db, actor_id), id=uuid4().hex, workspace_id=workspace_id, kind=kind, status="pending", message=message, progress=0.0)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_task(db: Session, task_id: str, **changes: object) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")
    for key, value in changes.items():
        setattr(task, key, value)
    task.updated_at = shanghai_now()
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def record_task_progress(
    session_factory: Callable[[], Session],
    task_id: str,
    *,
    progress: float | None = None,
    message: str | None = None,
    status: str | None = None,
    force: bool = False,
) -> None:
    """用独立短事务更新任务进度，避免把扫描自己的事务提前提交。"""
    terminal = status in {"completed", "failed", "canceled"}
    now = time.monotonic()
    if not force and not terminal:
        with _progress_lock:
            last = _last_progress_at.get(task_id, 0.0)
            if now - last < _PROGRESS_INTERVAL_SECONDS:
                return
    try:
        db = session_factory()
        try:
            changes: dict[str, object] = {}
            if progress is not None:
                changes["progress"] = progress
            if message is not None:
                changes["message"] = message
            if status is not None:
                changes["status"] = status
            if changes:
                update_task(db, task_id, **changes)
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to record task progress task_id=%s", task_id)
    with _progress_lock:
        if terminal:
            _last_progress_at.pop(task_id, None)
        else:
            _last_progress_at[task_id] = time.monotonic()


def fail_incomplete_tasks(
    db: Session,
    kind: str,
    message: str = "任务因服务重启中断，请重新提交。",
) -> int:
    now = shanghai_now()
    result = db.execute(
        update(Task)
        .where(Task.kind == kind, Task.status.in_(("pending", "running")))
        .values(status="failed", message=message, updated_at=now)
    )
    db.commit()
    return int(result.rowcount or 0)
