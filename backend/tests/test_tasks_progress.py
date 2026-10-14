from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Task
from app.services.tasks import record_task_progress


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
