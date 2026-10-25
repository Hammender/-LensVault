from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Task
from app.services.tasks import _last_progress_at, record_task_progress


def test_task_progress_uses_its_own_session_and_throttles() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with Session(engine) as db:
        db.add(Task(id="task-1", workspace_id=None, kind="gallery_import", status="pending", progress=0.0, message="排队"))
        db.commit()

    record_task_progress(factory, "task-1", progress=0.2, message="第一次", status="running", force=True)
    record_task_progress(factory, "task-1", progress=0.3, message="被节流", status="running")

    with Session(engine) as db:
        task = db.get(Task, "task-1")
    assert task is not None
    assert task.message == "第一次"
    assert task.progress == 0.2
    engine.dispose()


def test_task_progress_write_failure_does_not_advance_throttle() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    task_id = "task-progress-retry"
    _last_progress_at.pop(task_id, None)
    with Session(engine) as db:
        db.add(Task(id=task_id, workspace_id=None, kind="person_import", status="running", progress=0.0, message="开始"))
        db.commit()

    calls = {"n": 0}

    def session_factory() -> Session:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")
        return factory()

    wrote = record_task_progress(session_factory, task_id, progress=0.2, message="第一次失败", status="running")
    assert wrote is False
    assert calls["n"] == 1
    assert task_id not in _last_progress_at

    wrote = record_task_progress(session_factory, task_id, progress=0.6, message="立刻重试", status="running")
    assert wrote is True
    assert calls["n"] == 2
    with Session(engine) as db:
        task = db.get(Task, task_id)
    assert task is not None
    assert task.message == "立刻重试"
    assert task.progress == 0.6
    engine.dispose()
