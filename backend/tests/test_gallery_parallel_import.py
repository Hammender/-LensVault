from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Barrier, Lock
import time
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.background_tasks import process_gallery_import_task
from app.db import Base
from app.models import GalleryPhoto, Person, Task


class RecordingPictureService:
    def __init__(self, workers: int, barrier: Barrier | None = None, failing_payload: bytes | None = None) -> None:
        self.settings = SimpleNamespace(gallery_recognition_workers=workers)
        self.barrier = barrier
        self.failing_payload = failing_payload
        self.lock = Lock()
        self.active_recognitions = 0
        self.max_active_recognitions = 0
        self.recognized_payloads: list[bytes] = []
        self.imported_filenames: list[str] = []
        self.imported_plans: dict[str, object | None] = {}
        self.recognitions_active_during_import: list[int] = []
        self.manual_person_links: list[tuple[int, int, str]] = []

    def prepare_gallery_recognition(self, _db: Session, payload: bytes, _workspace_id: int) -> list[object]:
        with self.lock:
            self.active_recognitions += 1
            self.max_active_recognitions = max(self.max_active_recognitions, self.active_recognitions)
            self.recognized_payloads.append(payload)
        try:
            if self.barrier is not None:
                self.barrier.wait(timeout=3)
            else:
                time.sleep(0.02)
            if payload == self.failing_payload:
                raise RuntimeError("识别失败")
            return []
        finally:
            with self.lock:
                self.active_recognitions -= 1

    def import_gallery_photo(
        self,
        _db: Session,
        filename: str,
        _payload: bytes,
        _content_type: str | None,
        _tag_names: list[str],
        _rich_mode: bool,
        _rich_text: str | None,
        _workspace_id: int,
        *,
        recognition_plan: object | None,
    ) -> tuple[SimpleNamespace, SimpleNamespace]:
        with self.lock:
            self.recognitions_active_during_import.append(self.active_recognitions)
        self.imported_filenames.append(filename)
        self.imported_plans[filename] = recognition_plan
        photo_id = len(self.imported_filenames)
        return SimpleNamespace(id=photo_id), SimpleNamespace(known_matches=0, unknown_faces=0, duplicated=0)

    def ensure_gallery_person_tag(
        self,
        _db: Session,
        photo_id: int,
        person_id: int,
        source: str,
    ) -> None:
        self.manual_person_links.append((photo_id, person_id, source))

    def apply_person_tags_to_gallery_photo(self, *_args: object) -> None:
        return None


def _session_factory(tmp_path: Path, task_id: str):
    engine = create_engine(
        f"sqlite:///{tmp_path / f'{task_id}.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as db:
        db.add(Task(id=task_id, workspace_id=None, kind="gallery_import", status="pending", progress=0.0))
        db.commit()
    return engine, factory


def _run_import(factory, service: RecordingPictureService, task_id: str, uploads: list[tuple[str, bytes, str]]) -> None:
    process_gallery_import_task(
        factory,
        service,
        task_id,
        uploads,
        [{"person_ids": [], "tag_names": [], "rich_text": None} for _ in uploads],
        rich_mode=False,
        workspace_id=1,
    )


def test_recognition_overlaps_but_persistence_keeps_upload_order(tmp_path: Path) -> None:
    engine, factory = _session_factory(tmp_path, "parallel-order")
    service = RecordingPictureService(workers=2, barrier=Barrier(2))

    _run_import(factory, service, "parallel-order", [("a.jpg", b"a", "image/jpeg"), ("b.jpg", b"b", "image/jpeg")])

    assert service.max_active_recognitions == 2
    assert service.imported_filenames == ["a.jpg", "b.jpg"]
    assert service.recognitions_active_during_import == [0, 0]
    with factory() as db:
        assert db.get(Task, "parallel-order").status == "completed"
    engine.dispose()


def test_worker_configuration_can_force_serial_recognition(tmp_path: Path) -> None:
    engine, factory = _session_factory(tmp_path, "serial-workers")
    service = RecordingPictureService(workers=1)

    _run_import(factory, service, "serial-workers", [("a.jpg", b"a", "image/jpeg"), ("b.jpg", b"b", "image/jpeg")])

    assert service.max_active_recognitions == 1
    engine.dispose()


def test_existing_and_same_batch_duplicates_are_not_recognized(tmp_path: Path) -> None:
    engine, factory = _session_factory(tmp_path, "duplicate-filter")
    existing_payload = b"existing"
    with factory() as db:
        db.add(
            GalleryPhoto(
                workspace_id=1,
                filename="existing.jpg",
                sha256=hashlib.sha256(existing_payload).hexdigest(),
                object_key="gallery/existing.jpg",
                is_rich_text=False,
            )
        )
        db.commit()
    service = RecordingPictureService(workers=2)

    _run_import(
        factory,
        service,
        "duplicate-filter",
        [
            ("existing.jpg", existing_payload, "image/jpeg"),
            ("new-a.jpg", b"new", "image/jpeg"),
            ("new-b.jpg", b"new", "image/jpeg"),
        ],
    )

    assert service.recognized_payloads == [b"new"]
    engine.dispose()


def test_one_recognition_failure_does_not_block_other_imports(tmp_path: Path) -> None:
    engine, factory = _session_factory(tmp_path, "failure-isolation")
    service = RecordingPictureService(workers=2, failing_payload=b"bad")

    _run_import(
        factory,
        service,
        "failure-isolation",
        [("bad.jpg", b"bad", "image/jpeg"), ("good.jpg", b"good", "image/jpeg")],
    )

    assert service.imported_filenames == ["bad.jpg", "good.jpg"]
    assert service.imported_plans["bad.jpg"] is None
    assert service.imported_plans["good.jpg"] == []
    with factory() as db:
        assert db.scalar(select(Task).where(Task.id == "failure-isolation")).status == "completed"
    engine.dispose()


def test_multiple_existing_people_are_bound_as_preserved_manual_tags(tmp_path: Path) -> None:
    engine, factory = _session_factory(tmp_path, "multiple-people")
    with factory() as db:
        first = Person(workspace_id=1, name="张三", display_name="张三", is_unknown=False)
        second = Person(workspace_id=1, name="李四", display_name="李四", is_unknown=False)
        db.add_all([first, second])
        db.commit()
        person_ids = [first.id, second.id]
    service = RecordingPictureService(workers=1)

    process_gallery_import_task(
        factory,
        service,
        "multiple-people",
        [("group.jpg", b"group", "image/jpeg")],
        [{"person_ids": person_ids, "tag_names": [], "rich_text": None}],
        rich_mode=False,
        workspace_id=1,
    )

    assert service.manual_person_links == [
        (1, person_ids[0], "manual"),
        (1, person_ids[1], "manual"),
    ]
    with factory() as db:
        assert len(db.scalars(select(Person)).all()) == 2
    engine.dispose()
