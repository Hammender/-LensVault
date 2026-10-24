from __future__ import annotations

import logging
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.background_tasks import (
    process_gallery_import_task,
    process_gallery_zip_import_task,
    process_person_import_task,
)
from app.db import Base
from app.models import Task, UploadHistory


class FakePictureService:
    settings = SimpleNamespace(gallery_recognition_workers=2)

    def prepare_gallery_recognition(self, _db: Session, _payload: bytes, _workspace_id: int) -> list[object]:
        return []

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
        *,
        recognition_plan: object | None,
        actor_id=None, actor_name=None,
    ) -> tuple[SimpleNamespace, SimpleNamespace]:
        return SimpleNamespace(id=1), SimpleNamespace(known_matches=0, unknown_faces=0, duplicated=0)

    def ensure_gallery_person_tag(self, _db: Session, _photo_id: int, _person_id: int, _source: str) -> None:
        raise AssertionError("测试不应创建手动人物标签")

    def apply_person_tags_to_gallery_photo(self, _db: Session, _photo_id: int, _person_id: int) -> None:
        raise AssertionError("测试不应应用人物标签")


class FakeZipPictureService:
    def import_gallery_from_zip(
        self,
        _db: Session,
        _zip_bytes: bytes,
        _workspace_id: int,
        _progress_callback,
        *, actor_id=None, actor_name=None,
        person_tags="all", unknown_tag_source="import_unknown", recognize=False,
    ) -> dict[str, int]:
        self.received = {
            "person_tags": person_tags,
            "unknown_tag_source": unknown_tag_source,
            "recognize": recognize,
        }
        return {
            "added_photos": 2,
            "updated_existing": 1,
            "skipped_photos": 1,
            "tags_added": 0,
            "persons_added": 0,
            "recognized_known": 0,
            "recognized_unknown": 0,
            "option_summary": "人物：全部导入；未知：受保护",
        }


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
        [{"person_ids": [], "tag_names": [], "rich_text": "图文内容"}],
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


def test_gallery_zip_import_records_import_activity(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    task_id = "gallery-zip-import-task"

    with Session(engine) as db:
        db.add(Task(id=task_id, workspace_id=None, kind="gallery_zip_import", status="pending", progress=0.0))
        db.commit()

    monkeypatch.setattr("app.background_tasks.mark_similarity_scans_stale", lambda _db, _workspace_id: None)
    process_gallery_zip_import_task(
        session_factory,
        FakeZipPictureService(),
        task_id,
        b"zip",
        workspace_id=1,
    )

    with Session(engine) as db:
        history = db.scalar(select(UploadHistory).where(UploadHistory.upload_type == "gallery_zip"))
        task = db.get(Task, task_id)

    assert history is not None
    assert (history.total_count, history.success_count, history.duplicate_count) == (4, 3, 1)
    assert task is not None
    assert task.status == "completed"
    assert "人物：全部导入；未知：受保护" in (task.message or "")
    engine.dispose()


def test_gallery_zip_import_task_forwards_person_tag_options(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    task_id = "gallery-zip-import-options"
    service = FakeZipPictureService()

    with Session(engine) as db:
        db.add(Task(id=task_id, workspace_id=None, kind="gallery_zip_import", status="pending", progress=0.0))
        db.commit()

    monkeypatch.setattr("app.background_tasks.mark_similarity_scans_stale", lambda _db, _workspace_id: None)
    process_gallery_zip_import_task(
        session_factory,
        service,
        task_id,
        b"zip",
        workspace_id=1,
        person_tags="none",
        unknown_tag_source="unknown",
        recognize=True,
    )

    assert service.received == {
        "person_tags": "none",
        "unknown_tag_source": "unknown",
        "recognize": True,
    }
    with Session(engine) as db:
        task = db.get(Task, task_id)
    assert task is not None
    assert task.status == "completed"
    engine.dispose()


class FakePersonZipService:
    settings = SimpleNamespace(data_dir=None)

    def import_persons_from_zip(self, _db: Session, _zip_source, _workspace_id: int, progress_callback) -> dict[str, int]:
        progress_callback(1, 13)
        return {
            "created_persons": 1,
            "existing_persons": 0,
            "added_samples": 13,
            "skipped_samples": 0,
            "tags_added": 0,
        }


def test_person_import_task_completes_when_progress_recording_fails(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    task_id = "person-import-task"

    with Session(engine) as db:
        db.add(Task(id=task_id, workspace_id=None, kind="person_import", status="pending", progress=0.0))
        db.commit()

    def boom(*_args, **_kwargs) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr("app.background_tasks.record_task_progress", boom)
    process_person_import_task(session_factory, FakePersonZipService(), task_id, b"zip", workspace_id=1)

    with Session(engine) as db:
        task = db.get(Task, task_id)
    assert task is not None
    assert task.status == "completed"
    assert "创建 1 个人物" in (task.message or "")
    engine.dispose()
