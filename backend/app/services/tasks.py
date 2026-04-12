from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Task


def create_task(db: Session, kind: str, message: str | None = None) -> Task:
    task = Task(id=uuid4().hex, kind=kind, status="pending", message=message, progress=0.0)
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
    task.updated_at = datetime.utcnow()
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def fail_incomplete_tasks(
    db: Session,
    kind: str,
    message: str = "任务因服务重启中断，请重新提交。",
) -> int:
    now = datetime.utcnow()
    result = db.execute(
        update(Task)
        .where(Task.kind == kind, Task.status.in_(("pending", "running")))
        .values(status="failed", message=message, updated_at=now)
    )
    db.commit()
    return int(result.rowcount or 0)
