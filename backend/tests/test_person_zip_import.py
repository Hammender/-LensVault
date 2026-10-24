from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import tempfile
from zipfile import ZipFile

import numpy as np
from PIL import Image
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db import Base
from app.models import FaceRecord, Person, SamplePhoto, Task, Workspace
from app.services.face import DetectedFace
from app.services.importer import PersonImportPartialError, PictureService
from app.services.tasks import record_task_progress


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, object_key: str, payload: bytes, _content_type: str | None = None) -> None:
        self.objects[object_key] = payload


class SingleFaceService:
    def detect_faces(self, _payload: bytes) -> list[DetectedFace]:
        return [
            DetectedFace(
                (10, 10, 110, 110),
                0.99,
                np.ones(512, dtype=np.float32),
                100,
                90,
                0,
            )
        ]


class MemoryVectorStore:
    def __init__(self) -> None:
        self.faces: dict[int, np.ndarray] = {}
        self.centroids: dict[int, np.ndarray] = {}
        self.deleted_face_ids: list[list[int | str]] = []
        self.deleted_centroids: list[int] = []

    def upsert_face(
        self,
        _collection: str,
        face_id: int,
        _person_id: int,
        vector: np.ndarray,
        **_kwargs: object,
    ) -> None:
        self.faces[face_id] = np.asarray(vector, dtype=np.float32)

    def get_reference_vector(self, _collection: str, face_id: int, **_kwargs: object) -> np.ndarray:
        return self.faces[face_id]

    def upsert_centroid(
        self,
        _collection: str,
        person_id: int,
        vector: np.ndarray,
        **_kwargs: object,
    ) -> None:
        self.centroids[person_id] = np.asarray(vector, dtype=np.float32)

    def delete_centroid(self, _collection: str, _workspace_id: int | None, person_id: int, _version: str) -> None:
        self.deleted_centroids.append(person_id)
        self.centroids.pop(person_id, None)

    def delete_faces(self, _collection: str, face_ids: list[int | str]) -> None:
        self.deleted_face_ids.append(list(face_ids))
        for face_id in face_ids:
            self.faces.pop(face_id, None)  # type: ignore[arg-type]


class NoopOcrService:
    def extract_text(self, _payload: bytes) -> str:
        return ""


def _image_bytes(color: str) -> bytes:
    image = Image.new("RGB", (120, 120), color)
    source = BytesIO()
    image.save(source, format="JPEG")
    return source.getvalue()


def _person_zip(name: str, payloads: list[bytes]) -> bytes:
    source = BytesIO()
    with ZipFile(source, "w") as archive:
        samples = []
        for index, payload in enumerate(payloads, start=1):
            filename = f"{index}.jpg"
            archive.writestr(f"samples/{name}/{filename}", payload)
            samples.append(
                {
                    "filename": filename,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "content_type": "image/jpeg",
                    "width": 120,
                    "height": 120,
                }
            )
        archive.writestr(
            "metadata.json",
            json.dumps({"persons": [{"name": name, "display_name": name, "tags": [], "samples": samples}]}),
        )
    return source.getvalue()


def _file_sqlite_factory(tmp_dir: Path):
    engine = create_engine(
        f"sqlite:///{(tmp_dir / 'import.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 2},
    )

    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=2000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine, factory


class NoFaceService:
    def detect_faces(self, _payload: bytes) -> list[DetectedFace]:
        return []


def _make_service(
    face_service: object | None = None,
    vector_store: MemoryVectorStore | None = None,
) -> PictureService:
    return PictureService(  # type: ignore[arg-type]
        MemoryStorage(),
        face_service or SingleFaceService(),
        vector_store or MemoryVectorStore(),
        NoopOcrService(),
        Settings(),
    )


def _workspace(factory: sessionmaker[Session]) -> tuple[Session, int]:
    db = factory()
    workspace = Workspace(name="主空间")
    db.add(workspace)
    db.commit()
    return db, workspace.id


def test_person_zip_import_commits_before_progress_callback() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="pictureshow-person-import-"))
    engine, factory = _file_sqlite_factory(tmp_dir)
    archive = _person_zip("金米妮", [_image_bytes("white"), _image_bytes("gray")])
    db = factory()
    try:
        workspace = Workspace(name="主空间")
        db.add(workspace)
        db.flush()
        db.add(Task(id="person-import", workspace_id=workspace.id, kind="person_import", status="running", progress=0.0))
        db.commit()
        workspace_id = workspace.id
        seen_person: list[bool] = []
        progress_writes: list[str] = []

        def progress_callback(processed: int, total: int) -> None:
            other = factory()
            try:
                seen_person.append(other.scalar(select(Person).where(Person.name == "金米妮")) is not None)
                task = other.get(Task, "person-import")
                assert task is not None
                task.message = f"{processed}/{total}"
                other.commit()
                progress_writes.append(f"{processed}/{total}")
            finally:
                other.close()

        result = _make_service().import_persons_from_zip(db, archive, workspace_id, progress_callback)
        assert result["created_persons"] == 1
        assert result["added_samples"] == 2
        assert seen_person == [True, True]
        assert progress_writes == ["1/2", "2/2"]
        db.expire_all()
        person = db.scalar(select(Person).where(Person.workspace_id == workspace_id, Person.name == "金米妮"))
        assert person is not None
        samples = db.scalars(select(SamplePhoto).where(SamplePhoto.person_id == person.id)).all()
        assert len(samples) == 2
        assert {sample.status for sample in samples} == {"ready"}
    finally:
        db.close()
        engine.dispose()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_person_zip_import_keeps_person_when_progress_callback_fails() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="pictureshow-person-import-"))
    engine, factory = _file_sqlite_factory(tmp_dir)
    archive = _person_zip("金米妮", [_image_bytes("white")])
    db = factory()
    try:
        workspace = Workspace(name="主空间")
        db.add(workspace)
        db.commit()
        workspace_id = workspace.id

        def boom(_processed: int, _total: int) -> None:
            raise RuntimeError("database is locked")

        result = _make_service().import_persons_from_zip(db, archive, workspace_id, boom)
        assert result["created_persons"] == 1
        assert result["added_samples"] == 1
        db.expire_all()
        person = db.scalar(select(Person).where(Person.workspace_id == workspace_id, Person.name == "金米妮"))
        assert person is not None
        sample = db.scalar(select(SamplePhoto).where(SamplePhoto.person_id == person.id))
        assert sample is not None
        assert sample.status == "ready"
    finally:
        db.close()
        engine.dispose()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_record_task_progress_does_not_raise_when_update_fails() -> None:
    def broken_factory() -> Session:
        raise RuntimeError("database is locked")

    record_task_progress(broken_factory, "missing-task", progress=0.1, message="正在处理 1/13 个样本", force=True)


def _count_samples(factory: sessionmaker[Session]) -> int:
    other = factory()
    try:
        return len(other.scalars(select(SamplePhoto)).all())
    finally:
        other.close()


def test_person_zip_import_progress_due_commits_samples_with_centroid() -> None:
    """progress_due 第一次 False、第二次 True。

    第一次 progress_due 时另一会话看不到新样本。到期后先重算质心再提交，
    进度回调里才能看到样本。第二次进度回调开始时样本已可见，且质心已写入。
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="pictureshow-person-import-"))
    engine, factory = _file_sqlite_factory(tmp_dir)
    archive = _person_zip("金米妮", [_image_bytes("white"), _image_bytes("gray")])
    store = MemoryVectorStore()
    db, workspace_id = _workspace(factory)
    due_seen: list[tuple[bool, int]] = []
    callbacks: list[dict[str, object]] = []
    try:
        def progress_due() -> bool:
            visible = _count_samples(factory)
            due = len(due_seen) >= 1
            due_seen.append((due, visible))
            return due

        def progress_callback(processed: int, total: int) -> None:
            other = factory()
            try:
                person = other.scalar(select(Person).where(Person.workspace_id == workspace_id, Person.name == "金米妮"))
                samples = other.scalars(select(SamplePhoto)).all()
            finally:
                other.close()
            callbacks.append(
                {
                    "processed": f"{processed}/{total}",
                    "samples": len(samples),
                    "centroid": person is not None and person.id in store.centroids,
                }
            )

        result = _make_service(vector_store=store).import_persons_from_zip(
            db,
            archive,
            workspace_id,
            progress_callback,
            progress_due=progress_due,
        )
        assert result["added_samples"] == 2
        assert due_seen[0] == (False, 0)
        assert due_seen[1][0] is True
        assert due_seen[1][1] == 0
        assert [item["processed"] for item in callbacks] == ["1/2", "2/2"]
        assert callbacks[0]["samples"] == 1
        assert callbacks[0]["centroid"] is True
        assert callbacks[1]["samples"] == 2
        assert callbacks[1]["centroid"] is True
    finally:
        db.close()
        engine.dispose()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_person_zip_import_partial_failure_without_committed_samples() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="pictureshow-person-import-"))
    engine, factory = _file_sqlite_factory(tmp_dir)
    archive = _person_zip("金米妮", [_image_bytes("white")])
    store = MemoryVectorStore()
    service = _make_service(vector_store=store)
    db, workspace_id = _workspace(factory)

    def explode(_db: Session, _person_id: int, _workspace_id: int | None) -> None:
        raise RuntimeError("质心写入失败")

    service._recompute_person_centroid = explode  # type: ignore[method-assign]
    due_calls = {"n": 0}

    def progress_due() -> bool:
        due_calls["n"] += 1
        return due_calls["n"] >= 2

    try:
        with pytest.raises(PersonImportPartialError) as caught:
            service.import_persons_from_zip(db, archive, workspace_id, progress_due=progress_due)
        message = str(caught.value)
        assert caught.value.retained_samples == 0
        assert message.startswith("导入中断：尚未写入样本。原因：")
        assert "质心写入失败" in message
        assert "已保留" not in message
        other = factory()
        try:
            assert other.scalar(select(SamplePhoto)) is None
            assert other.scalar(select(Person).where(Person.name == "金米妮")) is None
        finally:
            other.close()
        assert store.faces == {}
        assert store.deleted_face_ids
        assert store.deleted_face_ids[0]
    finally:
        db.close()
        engine.dispose()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_person_zip_import_partial_failure_keeps_committed_samples() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="pictureshow-person-import-"))
    engine, factory = _file_sqlite_factory(tmp_dir)
    archive = _person_zip("金米妮", [_image_bytes("white"), _image_bytes("gray")])
    store = MemoryVectorStore()
    service = _make_service(vector_store=store)
    original = service._recompute_person_centroid
    calls = {"n": 0}

    def explode(db: Session, person_id: int, workspace_id: int | None):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("质心写入失败")
        return original(db, person_id, workspace_id)

    service._recompute_person_centroid = explode  # type: ignore[method-assign]
    db, workspace_id = _workspace(factory)
    try:
        with pytest.raises(PersonImportPartialError) as caught:
            service.import_persons_from_zip(db, archive, workspace_id)
        message = str(caught.value)
        assert caught.value.retained_samples == 1
        assert "已保留 1 个样本" in message
        assert "已提交批次的人物质心已更新" in message
        assert "质心写入失败" in message
        assert message.startswith("导入中断：已保留 1 个样本")
        other = factory()
        try:
            samples = other.scalars(select(SamplePhoto)).all()
            assert len(samples) == 1
            assert samples[0].status == "ready"
            person = other.scalar(select(Person).where(Person.workspace_id == workspace_id, Person.name == "金米妮"))
            assert person is not None
            assert person.id in store.centroids
            face = other.scalar(select(FaceRecord).where(FaceRecord.sample_photo_id == samples[0].id))
            assert face is not None
            assert face.id in store.faces
            deleted = [face_id for batch in store.deleted_face_ids for face_id in batch]
            assert deleted
            assert face.id not in deleted
            assert set(deleted).isdisjoint(store.faces)
        finally:
            other.close()
    finally:
        db.close()
        engine.dispose()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_person_zip_import_clears_centroid_when_new_person_has_no_ready_samples() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="pictureshow-person-import-"))
    engine, factory = _file_sqlite_factory(tmp_dir)
    archive = _person_zip("金米妮", [_image_bytes("white")])
    store = MemoryVectorStore()
    db, workspace_id = _workspace(factory)
    try:
        result = _make_service(NoFaceService(), store).import_persons_from_zip(db, archive, workspace_id)
        assert result["created_persons"] == 1
        assert result["added_samples"] == 1
        db.expire_all()
        person = db.scalar(select(Person).where(Person.workspace_id == workspace_id, Person.name == "金米妮"))
        assert person is not None
        sample = db.scalar(select(SamplePhoto).where(SamplePhoto.person_id == person.id))
        assert sample is not None
        assert sample.status == "no_face"
        assert person.id in store.deleted_centroids
        assert person.id not in store.centroids
    finally:
        db.close()
        engine.dispose()
        shutil.rmtree(tmp_dir, ignore_errors=True)
