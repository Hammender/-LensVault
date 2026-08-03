from __future__ import annotations

import logging
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.background_tasks import process_gallery_import_task
from app.db import Base
from app.models import Task, UploadHistory


class FakePictureService:
    def import_gallery_photo(
        self,
        _db: Session,
        _filename: str,
        _payload: bytes,
        _content_type: str | None,
        _tag_names: list[str],
        _rich_mode: bool,
        _rich_text: str | None,
        _workspace_id: int,
    ) -> tuple[SimpleNamespace, SimpleNamespace]:
        return SimpleNamespace(id=1), SimpleNamespace(known_matches=0, unknown_faces=0, duplicated=0)

    def ensure_gallery_person_tag(self, _db: Session, _photo_id: int, _person_id: int, _source: str) -> None:
        raise AssertionError("测试不应创建手动人物标签")

    def apply_person_tags_to_gallery_photo(self, _db: Session, _photo_id: int, _person_id: int) -> None:
        raise AssertionError("测试不应应用人物标签")


def test_gallery_import_records_upload_history_without_log_format_error(caplog) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    task_id = "gallery-import-task"

    with Session(engine) as db:
        db.add(Task(id=task_id, workspace_id=None, kind="gallery_rich_import", status="pending", progress=0.0))
        db.commit()

    caplog.set_level(logging.INFO, logger="app.background_tasks")
    process_gallery_import_task(
        session_factory,
        FakePictureService(),
        task_id,
        [("photo.jpg", b"image", "image/jpeg")],
        [{"person_names": [], "tag_names": [], "rich_text": "图文内容"}],
        rich_mode=True,
        workspace_id=1,
    )

    with Session(engine) as db:
        history = db.scalar(select(UploadHistory))
        task = db.get(Task, task_id)

    history_record = next(record for record in caplog.records if record.msg.startswith("Upload history recorded"))
    assert history_record.getMessage() == "Upload history recorded upload_type=rich total=1 success=1 duplicate=0"
    assert history is not None
    assert (history.upload_type, history.total_count, history.success_count, history.duplicate_count) == ("rich", 1, 1, 0)
    assert task is not None
    assert task.status == "completed"
    engine.dispose()
