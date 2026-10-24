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


def task_progress_due(task_id: str, *, force: bool = False, status: str | None = None) -> bool:
    """非终态进度约 1 秒才到期。未到期时调用方不应再开写事务。"""
    terminal = status in {"completed", "failed", "canceled"}
    if force or terminal:
        return True
    now = time.monotonic()
    with _progress_lock:
        return now - _last_progress_at.get(task_id, 0.0) >= _PROGRESS_INTERVAL_SECONDS


def record_task_progress(
    session_factory: Callable[[], Session],
    task_id: str,
    *,
    progress: float | None = None,
    message: str | None = None,
    status: str | None = None,
    force: bool = False,
) -> bool:
    """用独立短事务更新任务进度，避免把扫描自己的事务提前提交。

    返回是否写入成功。未到期直接返回 False，不改节流时间。
    只有 update_task 成功才推进节流；写入失败留在原时间，便于立刻重试。
    终态无论成败都清掉节流槽。
    """
    terminal = status in {"completed", "failed", "canceled"}
    if not task_progress_due(task_id, force=force, status=status):
        return False
    wrote = False
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
                wrote = True
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to record task progress task_id=%s", task_id)
    with _progress_lock:
        if terminal:
            _last_progress_at.pop(task_id, None)
        elif wrote:
            _last_progress_at[task_id] = time.monotonic()
    return wrote


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
